"""The HTTP door onto usage: the report and the meter vocabulary, both reads (ADR usage-1, § Doors).

# why-not a write route: a client that could send usage could mint or dispute its own bill.
# why-not `from __future__ import annotations`: ninja reads the route signatures at import.
"""

from datetime import UTC, date, datetime, time
from typing import Annotated

from django.utils import timezone
from ninja import Query, Router
from ninja.params.functions import Query as QueryParam

from apps.accounts.auth import API_AUTH
from apps.core.actor import Actor
from apps.core.api.acting import acting
from apps.core.api.docs import Tag, refuses
from apps.core.api.pagination import MAX_LIMIT, cursor_page
from apps.core.models import Tenant
from apps.core.requests import TenantRequest
from apps.usage import meters as meter_registry
from apps.usage.schemas import MeterOut, MeterPage, UsageReportOut
from apps.usage.selectors import get_usage
from apps.usage.types import Period, PeriodKind

#: Two resources, so no `PREFIX` (ADR api-2): `/api/v1/usage/` and `/api/v1/meters/`.
PREFIX = ""

#: The scope family (ADR ident-7): `usage`, rule 16's recorded mass noun; there is no write half.
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

router = Router(tags=["usage"], auth=API_AUTH)


def meter_catalogue() -> list[MeterOut]:
    """Every meter this deployment declares, by name — the vocabulary `record_usage` holds to."""
    return sorted(
        (
            MeterOut(name=name, app=app_label)
            for app_label, names in meter_registry.declared_meters().items()
            for name in names
        ),
        key=lambda entry: entry.name,
    )


def _window(*, period: PeriodKind, on: date | None) -> Period:
    """The window a report covers; `on=None` is today in UTC (`types.Period`'s ruling).

    Shared by both doors: two calendars would be two answers to one question about money.
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
    """One window's totals, in the shape both doors put on the wire; an undeclared meter is refused.

    `ends_on` is the last day covered: `Period` is half-open, a reader's month ends on the 31st.
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
    send that we cannot resolve is refused** (`403 addressing_header_not_honoured`)
    rather than quietly ignored: a mistyped hat must never come back as a bill of
    zero.

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
    * `403 no_acting_scope` — the request resolved no tenant. Send an `X-Tenant`
      naming one you belong to.
    * `403 addressing_header_not_honoured` — the `X-Tenant` or `X-Org` you sent
      is not one you can act as. Name one you belong to, or send neither and act
      as your defaults.
    * `403 forbidden` — this credential may not read usage.
    * `403 insufficient_scope` — the token authenticated and its ceiling does
      not carry `usage:read`. Mint one that does.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    why-not `@paginate`: one report object, one grouped aggregate — not a collection.
    """
    actor, tenant = acting(request)
    return report(tenant=tenant, actor=actor, period=period, on=on, meters=meters)


# --- The vocabulary -----------------------------------------------------------


def meter_page(
    *,
    tenant: Tenant | None,
    cursor: str | None,
    limit: int | None,
    include_count: bool,
) -> MeterPage:
    """One page of the vocabulary, in the shape both doors put on the wire."""
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
    # The ceiling, published: bare parameters inherit no `Input` schema.
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
    why-not a query pin: this route reads no table — the population is the installed `meters.py`.
    why-not `acting`: the vocabulary is the deployment's, not a tenant's — nothing to scope.
    """
    return meter_page(
        tenant=getattr(request, "tenant", None),
        cursor=cursor,
        limit=limit,
        include_count=include_count,
    )
