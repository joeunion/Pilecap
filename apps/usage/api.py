"""The HTTP door onto usage: two routes, and both of them read.

**There is no write capability here and there will not be one** (ADR usage-1,
§ Doors). A client that could send a usage body could mint or dispute its own
bill, so `services.record_usage` is reached from activities and services and
from no route and no tool — `services.py` carries rule 42's `# door:` line with
that reason, and `tests/test_api.py::test_there_is_no_write_door` is what keeps
the absence a decision rather than a gap somebody fills in later. Disputes are
the operator's: a customer who thinks a number is wrong asks a person, and the
correction is a superseding row somebody made deliberately.

**The second route is the vocabulary, and it arrived because the first one
needed it.** `GET /usage/?meters=not.a.meter`
answered `200` zero-filled while this operation's own contract promised the
zero-filling existed "so you can tell none from I asked the wrong question" —
which it did not, and could not, because there was nowhere to find out what the
meters ARE. `apps/usage/meters.py` calls itself "declared vocabulary, exactly as
event names are"; `/api/v1/event-types/` and `list_event_types` are what that
sentence looks like when it is true, and `/api/v1/meters/` and `list_meters` are
the same pair for meters. The two halves land together on purpose: refusing an
undeclared name without publishing the declared ones would be a closed set
nobody can read.

The read goes through `selectors.get_usage`, which authorizes (`usage.read`) and
narrows `.for_tenant(t).visible_to(actor)` — both halves, so a branch's report
never tallies a sibling's consumption and an unresolved hat reads an empty
ledger rather than the ledger. Nothing here re-decides any of that; the route
resolves who is asking and what window they asked about, and that is all a door
is allowed to be.

`_window` below is shared with `mcp.py` rather than written twice, for the same
reason `apps/exports/api.py::downloadable_export` is: the two doors would
otherwise be free to come to different opinions about which month "this month"
is, and a disagreement about a window is a disagreement about a bill.
"""

# NOTE: no `from __future__ import annotations` in this module, and that is
# deliberate. ninja builds a Pydantic model out of a route's signature at import
# time; with postponed evaluation every annotation is a string, and a parameter
# whose type it cannot resolve comes out as an unresolvable forward reference.

from datetime import UTC, date, datetime, time
from typing import Annotated

from django.utils import timezone
from ninja import Query, Router
from ninja.errors import HttpError
from ninja.params.functions import Query as QueryParam

from apps.accounts.auth import API_AUTH
from apps.core.actor import Actor, actor_from_request
from apps.core.api.docs import Tag, refuses
from apps.core.api.pagination import MAX_LIMIT, cursor_page
from apps.core.exceptions import Forbidden, Remedy
from apps.core.middleware import ORG_HEADER
from apps.core.models import Organization, Tenant
from apps.core.requests import TenantRequest
from apps.usage import meters as meter_registry
from apps.usage.schemas import MeterOut, MeterPage, UsageReportOut
from apps.usage.selectors import get_usage
from apps.usage.types import Period, PeriodKind

# **This app serves two resources, so it names neither in a `PREFIX`** — the
# same shape `apps/events` uses (ADR api-2, the owner's ruling: the
# first path segment names a RESOURCE, never an app). The report is at
# `/api/v1/usage/` and the vocabulary it is read against is at
# `/api/v1/meters/`, which is where a caller would look for it: a meter is not
# a kind of usage, it is the thing usage is counted in, and hiding the
# catalogue under the report's noun would be the URL saying which module of
# ours serves it.
#
# The report's own path is unchanged and `tests/test_api.py::
# test_the_route_is_mounted_where_the_document_says` is the pin: `usage` is a
# declared coincidence in `quality/rules.yaml` under rule 32's
# `allowed_label_paths` — a mass noun (rule 16's recorded app-name exception)
# and also the word a caller already has for what the report returns — so
# moving it would make the URL worse to satisfy a rule about URLs.
PREFIX = ""

# The scope family, and it is the ratified key from RUL-1 — `usage`, the same
# string as the app label and as the first segment of the path. It follows the
# EXCEPTION half of the choosing pattern (django-conventions §6) in the mildest
# possible way: the default is the plural noun of the section's primary
# resource, and this section's noun has no plural that means anything ("usages"
# is a word about senses of a word). House rule 16 already carries that as this
# app's recorded naming exception, and the family key inherits it rather than
# inventing a second spelling — `usage:read` is what a token holding it is
# trusted with, said to somebody reading the string with no API around it.
#
# The key FREEZES the day a token could name it, which is today: renaming it
# later kills every ceiling that holds it, silently, while the token goes on
# authenticating and starts being refused at every door. `FROZEN_FAMILIES` in
# `apps/core/api/scopes.py` is the census this is written into in the same
# commit.
#
# There is no `usage:write` anywhere in this deployment and there is no way to
# ask for one: the vocabulary is families crossed with the two verb classes, so
# the string exists — and nothing it could reach does.
TAGS = {
    "usage": Tag(
        "Usage",
        "What this account has consumed, measured and shown. Every meter is a "
        "count of things used — tokens, bytes, messages — reported for a day or "
        "a month with the daily subtotals it was added up from. Meters record "
        "quantities and never prices, and nothing here can be written: usage is "
        "recorded by the platform as it happens, and a figure you disagree with "
        "is a conversation with us rather than a request you can send.",
        plane="everyday",
        plane_note=(
            "what your organization has consumed, meter by meter, with the daily subtotals each "
            "total was added up from. Everyday rather than administrative for the same reason "
            "`exports` is: a report covers the part of the tree you are acting in, so it tells "
            "you nothing you could not have added up yourself from the rows you can already "
            "read. **Read-only, and it is the one section with no write side at all** — "
            "consumption is recorded by the platform as it happens, so a write half reaches "
            "nothing and nobody needs to ask for it."
        ),
    ),
}

# `auth` is restated here rather than inherited from the API default, so that
# reading this one file tells you what it takes to call this route.
router = Router(tags=["usage"], auth=API_AUTH)


def require_resolved_hat(*, requested_slug: str | None, org: Organization | None) -> None:
    """A hat that was **sent** and did not resolve is refused. Shared by both doors.

    **The zero-bill hazard, closed at this door.**
    `core.middleware.resolve_org` fails closed to `None` for an unknown slug, a
    slug in another tenant, and a node the caller holds no role over — which is
    the right posture for a *read of rows*, because `visible_to(None)` then
    returns nothing. On a **bill** it is the wrong answer said convincingly: a
    fat-fingered `X-Org` came back `200 {"meters": {}}`, and "you consumed
    nothing" is a sentence a customer acts on. Nothing anywhere noticed that a
    hat had been sent and not honoured, because `None` is also what "no hat was
    sent" looks like by the time a route sees it.

    So the door reads the header itself — by its declared name (rule 40:
    `core.middleware.ORG_HEADER`, imported, never re-spelled) — and asks the one
    question the resolved value cannot answer: *was one asked for?* Sent and
    unresolved is `403 forbidden`, which is what this operation's contract has
    always promised. Not sent is untouched: the caller's default node, exactly
    as before.

    **Door-local, deliberately, and the sibling is booked rather than fixed.**
    Every other door in the product inherits the same silence, and closing it
    for all of them is a change to `resolve_org` — a core seam, in a wave where
    the ingredient apps make zero core edits. That is a named residual for the
    next core window and not this app's to take.

    It is a module-level function rather than a branch inside `_acting` because
    the MCP twin needs the same decision and a second copy of it is how two
    doors come to disagree about the same header (rule 46's whole subject).
    """
    if requested_slug and requested_slug.strip() and org is None:
        raise Forbidden(
            f"The organization {requested_slug.strip()!r} is not one you can act as, so "
            f"there is no report to give you. Send an {ORG_HEADER} naming an organization "
            f"you hold a membership on or above, or send none and act as your default.",
            remedies=(
                Remedy("Name an organization you belong to", f"header:{ORG_HEADER}"),
                Remedy("List the organizations you can act as", "route:organization-list"),
            ),
        )


def _acting(request: TenantRequest) -> tuple[Actor, Tenant]:
    """The actor and tenant this read happens as.

    Authentication has already guaranteed the user. The tenant has not been
    guaranteed by anything: a signed-in user with no membership resolves to
    `None`, and a report with no tenant is refused rather than guessed at.

    The hat rides on the actor, which is where `selectors.get_usage` reads it
    from — there is no `organization=` argument for a caller to forge. What this
    DOES ask about is the header, because the actor cannot: see
    `require_resolved_hat`.
    """
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")
    require_resolved_hat(
        requested_slug=request.headers.get(ORG_HEADER), org=getattr(request, "org", None)
    )
    return actor_from_request(request), request.tenant


def meter_catalogue() -> list[MeterOut]:
    """Every meter this deployment declares — **one implementation, both doors**.

    It lives here rather than in `selectors.py` because it does not return a
    queryset: it reads no table at all. The population is the installed apps'
    own `meters.py` declarations (`meters.declared_meters()`), which is the same
    registry `record_usage` validates a write against and the same one the read
    door refuses an unknown `?meters=` against — so the vocabulary a caller is
    held to is the vocabulary it can read.

    **Derived, so it cannot rot.** A hand-listed catalogue is wrong the morning
    after the next app declares a meter, and nothing fails. This is a census, so
    the day `apps/completions` declares `completions.tokens.input`, the
    catalogue has it and no file here changed.

    It is the same for every tenant on the deployment, deliberately: the
    vocabulary is the product's, not a customer's data. What a given tenant has
    actually SPENT is the report.

    Sorted by name, so the page a client gets back is stable between calls and
    two pages of it do not overlap.
    """
    return sorted(
        (
            MeterOut(name=name, app=app_label)
            for app_label, names in meter_registry.declared_meters().items()
            for name in names
        ),
        key=lambda entry: entry.name,
    )


def _window(*, period: PeriodKind, on: date | None) -> Period:
    """The window a report covers, from the two things a caller may say.

    **Shared by both doors, deliberately.** REST and MCP each hand it a period
    kind and an optional day; neither is free to decide what "this month" means,
    because two doors with two calendars is two answers to one question about
    money.

    `on=None` is *today in UTC*, and UTC rather than the tenant's timezone is
    `types.Period`'s ruling carried up to the door: a total that moved when a
    customer relocated would not be evidence. A caller who wants a local
    calendar names the day they mean.
    """
    day = timezone.now().astimezone(UTC).date() if on is None else on
    return Period.containing(datetime.combine(day, time.min, tzinfo=UTC), period)


def report(
    *,
    tenant: Tenant,
    actor: Actor,
    period: PeriodKind,
    on: date | None,
    meters: list[str] | None,
) -> UsageReportOut:
    """One window's totals, in the shape both doors put on the wire.

    The window and the body are built here rather than in each door, so that the
    two cannot come to describe the same report differently — the disagreement
    house rule 46's parity test exists to catch, prevented one layer earlier by
    there being one place that builds it.

    `ends_on` is the LAST day covered rather than the first day not covered:
    `Period` is half-open internally because a closed window double-counts the
    boundary instant, and a person reading a report expects the month to end on
    the thirty-first.

    **The vocabulary is checked here too, and that is the point of "here":**
    a meter no installed app declares is refused rather than zero-filled,
    so a typo and a real meter sitting at zero stop being the same answer. It is
    checked in this function rather than in each door for the same reason the
    window is — two doors free to hold two vocabularies is two answers to one
    question about a bill.
    """
    if meters is not None:
        meter_registry.check_reported_meters(meters)
    window = _window(period=period, on=on)
    return UsageReportOut(
        period=period.value,
        starts_on=window.starts_at.date(),
        ends_on=window.days()[-1],
        meters=get_usage(tenant=tenant, actor=actor, period=window, meters=meters),
    )


@router.get("/usage/", response=UsageReportOut, url_name="usage-detail")
def usage_report_route(
    request: TenantRequest,
    period: PeriodKind = PeriodKind.MONTH,
    on: date | None = None,
    meters: Query[list[str] | None] = None,
) -> UsageReportOut:
    """Retrieve a usage report

    What your organization has consumed in one window, meter by meter, with the
    daily subtotals each total was added up from.

    **A meter counts things used** — tokens, bytes, messages — under a name like
    `files.storage.bytes`. Every quantity here is a **quantity and never a
    price**: what any of it costs is not something this endpoint knows or says.
    Which meters exist is not something to guess at: `GET /meters/` lists every
    one this deployment declares, and a name that is not on that list is refused
    here rather than answered with zero.

    **Choose the window** with `period`, which is `month` (the default) or
    `day`, and `on`, which is any date inside the window you want — send
    `?period=month&on=2026-08-12` for the whole of that August. Leave `on` out
    and you get the window containing today. Windows are counted in **UTC**, so
    a report never changes because somebody moved.

    **Narrow to particular meters** by repeating `meters`:
    `?meters=files.storage.bytes`. A meter you name
    that recorded nothing comes back at zero rather than being left out, so you
    can tell "none" from "I asked the wrong question" — and a meter this
    deployment does not declare is **refused** (`400 invalid`, naming what is
    declared) rather than zero-filled, which is the other half of being able to
    tell those apart. Name none and you get whatever the window actually holds.

    **Every number is a JSON string**, not a JSON number — `"1240.0000"`, not
    `1240` — so that no client's float handling can change a figure on the way
    in. Parse them as decimals.

    Each meter's total is a **measured** number: `value` is the window's total,
    `basis.formula` is the string `sum(day_totals)`, and `basis.inputs` maps
    every date in the window to that day's subtotal — including the days that
    contributed nothing, so you can check the arithmetic without asking a second
    question. Add the inputs up and you get the value.

    **What you can see** depends on the organization you are acting as — the
    `X-Org` header, or your default organization if you send none. You get that
    organization's consumption and that of every organization beneath it. A
    branch alongside yours, or above it, is not in the total. **An `X-Org` you
    send that we cannot resolve is refused** (`403 forbidden`) rather than
    quietly ignored: a mistyped hat must never come back as a bill of zero.

    **There is no way to write usage here, and that is deliberate.** Consumption
    is recorded by the platform as it happens, so nothing you send could add to
    it or take away from it — a figure you believe is wrong is a conversation
    with us, and the correction is a new entry that says what it corrects and
    why, leaving both readable.

    Refusals you can get here:

    * `400 invalid` — `period` was something other than `day` or `month`, `on`
      was not a date, or a `meters` entry is not a meter this deployment
      declares. The response says which parameter, and for a meter it says what
      the vocabulary is and where to list it.
    * `403 forbidden` — the request resolved no tenant, or the `X-Org` you sent
      is not one you can act as, or this credential may not read usage. Send an
      `X-Tenant` and an `X-Org` naming ones you belong to, or send neither and
      act as your defaults.
    * `403 insufficient_scope` — the token authenticated and its ceiling does
      not carry `usage:read`. Mint one that does.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    Not `@paginate`d, and that is not an omission house rule 3 should catch: the
    answer is a single report object rather than a collection, and there is no
    list shape anywhere in `selectors.py` to paginate — `get_usage` returns one
    mapping of meter to total, computed by one grouped aggregate whose cost does
    not grow with the number of days or meters (`tests/test_selectors.py`'s
    `READ_QUERY_BUDGET`). The day a rung publishes the ENTRIES themselves, that
    route is a list and owes `CursorPagination`; this one would be paginating a
    dictionary with one key per meter.

    `meters` is wrapped in `Query[...]` and the other two are not: ninja reads a
    scalar with a default as a query parameter already, and a LIST needs saying
    out loud or it would be looked for in the body of a `GET`.
    """
    actor, tenant = _acting(request)
    return report(tenant=tenant, actor=actor, period=period, on=on, meters=meters)


# --- The vocabulary -----------------------------------------------------------


def meter_page(
    *,
    tenant: Tenant | None,
    cursor: str | None,
    limit: int | None,
    include_count: bool,
) -> MeterPage:
    """One page of the vocabulary, in the shape both doors put on the wire.

    The twin of `report` above, and it exists for the same reason: two doors free
    to assemble one answer are two doors that will eventually assemble it
    differently. `cursor_page` is the one paginator (ADR core-18) and this is the
    one call to it, so the envelope, the cursor's signing and the tenant binding
    are decided once for REST and MCP together.
    """
    page = cursor_page(
        meter_catalogue(),
        tenant=tenant,
        cursor=cursor,
        limit=limit,
        include_count=include_count,
        ordering=("name",),
    )
    return MeterPage(
        items=list(page.items),
        has_more=page.has_more,
        next_cursor=page.next_cursor,
        count=page.count,
    )


@router.get("/meters/", response=MeterPage, url_name="meter-list")
@refuses("insufficient_scope", "invalid_cursor", "not_found", "rate_limited")
def list_meters_route(
    request: TenantRequest,
    cursor: str | None = None,
    # The ceiling, PUBLISHED. This route takes its pagination
    # controls as bare parameters rather than through
    # `@paginate(CursorPagination)`, so it does not inherit the
    # `Input` schema that declares them — which is why the derived pass in
    # `apps/core/tests/test_pagination.py` found it. The refusal it already
    # inherits: `cursor_page` refuses an over-limit page for every caller,
    # both doors. `MAX_LIMIT` is imported rather than typed so the number
    # is still spelled in exactly one place.
    limit: Annotated[int | None, QueryParam(None, ge=1, le=MAX_LIMIT)] = None,
    include_count: bool = False,
) -> MeterPage:
    """List meters

    List every meter this deployment counts things under.

    Returns `{"items": [{"name": ..., "app": ...}], "has_more": ...,
    "next_cursor": ...}`, sorted by name, walked with `?cursor=` and `?limit=`
    (50 at a time by default, 200 at most). `count` arrives only with
    `?include_count=true`.

    **A meter counts things used** — tokens, bytes, messages — under a name that
    reads `<area>.<thing>.<unit>`, for example `files.storage.bytes`, and `app`
    tells you which part of the product spends it. Every value you can put in
    `GET /usage/?meters=` is here; anything else is refused there rather than
    answered with a zero, so this list is how you tell a meter that recorded
    nothing from a name we do not have.

    This list is generated from the running system, so it is always the complete
    and current set. It is the same for every customer: it describes what the
    product can meter, not what you happen to have consumed. **A quantity is
    never a price** — what any of this costs is not something these endpoints
    know or say.

    Refusals you can get here:

    * `403 insufficient_scope` — the token you sent does not carry the scope
      this read needs. Reading is not role-gated: this is the product's own
      vocabulary, the same for every customer, and any member may read it.
    * `400 invalid_cursor` — the `?cursor=` was edited, or came from a different
      endpoint. Start the walk again without one.
    * `404 not_found` — the cursor was minted for a different account.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    Ordered by name in `meter_catalogue()`, which is what makes paging over it
    stable; there is no ordering parameter because there is nothing else to
    order by. **No query pin and no query budget**, and that is not an omission
    rule 5 should catch: this route reads no table at all — the population is
    the installed apps' own `meters.py` modules off the live app registry — so
    there is no statement whose count could grow with the number of rows.

    **There is no `@paginate` here either**, and that is the same decision
    `apps/search/api.py` records for the same reason plus one of its own: there
    is no queryset for the paginator to slice, so the CURSOR SEAM is used
    directly (`meter_page` → `core.api.pagination.cursor_page`, where the
    signing, the tenant binding and the ordering check live) and both doors
    return the one `MeterPage`. `MeterPage`'s own docstring carries the second
    reason — a `@paginate`d wrapper cannot carry a declared example on `items`,
    and house rule 41's census counts every one of them.

    No `_acting` here, unlike the report: the vocabulary is the deployment's and
    not a tenant's, so there is nothing to scope and nothing a hat could narrow —
    including a hat that did not resolve, which is why this route does not carry
    the report's `403`. The credential is still required (the router's `auth=`)
    because an anonymous caller learning which meters a product bills on is a
    fact about the product we have not decided to publish.
    """
    return meter_page(
        tenant=getattr(request, "tenant", None),
        cursor=cursor,
        limit=limit,
        include_count=include_count,
    )
