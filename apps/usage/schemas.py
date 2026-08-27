"""The shapes this app publishes. **Four `Out`s and no `In`, and that is the ADR.**

There is no request schema here because there is no write door and there will not
be one: a client that could send a usage body could mint or dispute its own bill
(ADR usage-1, § Doors — "deliberately door-less: writes"). What travels outward
is what the **event** carries and what the read door answers with — and an event
payload is a published contract exactly as a route's response body is, which is
why `emit` sends the schema rather than the model, the way every app here does:
a webhook subscriber and a REST client should see one shape for one fact.

`UsageReportOut` declares an example on every one of its fields (house rule
41): a synthesised example can say that a total is a string, and only a declared
one can show a reader that the string is a QUANTITY — a count of things
consumed, never a price. This app has no opinion about money.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field

from apps.core.schemas import ListPage, MeasuredBasisOut, MeasuredOut, example
from apps.usage import meters as meter_registry

__all__ = [
    "MeasuredBasisOut",
    "MeasuredOut",
    "MeterOut",
    "MeterPage",
    "ThresholdCrossingOut",
    "UsageEntryOut",
    "UsageReportOut",
]


def _declared_meters_example(schema: dict[str, Any]) -> None:
    """Key the report's example on a meter this deployment actually declares.

    **The one derived example in the tree, and it is derived because a constant
    here is a refusal a stranger meets on their first copy-paste.** The old
    example was keyed `completions.tokens.input`, written when the read door
    zero-filled whatever it was handed; the undeclared-meter refusal turned it
    into a `400` in the OpenAPI document, the reference page and
    `get_usage.outputSchema` at once. Keying it on
    today's one declared meter would fix today and rot the same way — silently,
    the day the vocabulary moves — so the key comes from the registry the
    catalogue route publishes and the read door refuses against. Three views,
    one source.

    **A callable rather than `example(...)`, and that is what buys the
    property.** `core.schemas.example` returns `{"example": value}` at class
    definition time, and at class definition time this module has no business
    walking the app registry: `apps/usage/schemas.py` is imported while the
    doors are being discovered, and a registry read there would be right only by
    luck about import order. Pydantic calls a `json_schema_extra` callable while
    it BUILDS the JSON schema — which is document-render time, long after every
    app is loaded — and the document is rebuilt per call (`ninja.openapi.
    get_schema` constructs a fresh `OpenAPISchema`), so nothing caches a stale
    vocabulary into a published contract. Rule 41's census reads the `example`
    key off the finished document, so this counts as declared exactly as a
    literal would.

    **An empty example when nothing is declared**, said once here and argued in
    `meters.example_meter`: a deployment with no meters has a read door that can
    only answer `{}`, and there is no name this could show that the door would
    not refuse.
    """
    meter = meter_registry.example_meter()
    if meter is None:
        schema["example"] = {}
        return
    schema["example"] = {
        meter: {
            "value": "1240.0000",
            "basis": {
                "formula": "sum(day_totals)",
                "inputs": {"2026-08-01": "0.0000", "2026-08-02": "1240.0000"},
            },
        }
    }


class MeterOut(Schema):
    """One meter this deployment declares, and the app that declares it.

    **Derived, never listed** — the same shape and the same argument as
    `events.schemas.EventTypeOut`, because it is the same kind of thing: a
    published vocabulary read off the installed apps' own `meters.py` modules at
    request time (`usage.meters.declared_meters()`). That is the registry
    `record_usage` validates a write against and the registry the read door now
    refuses an unknown name against, so a caller picks from what actually
    exists and the catalogue cannot rot the day another app declares a meter.

    Two fields and no third. There is no `description` here and it is not an
    omission: a meter's declaration is a string constant, its meaning is the
    declaring module's docstring, and a description field would be a second
    place to say what `files.storage.bytes` counts — one that a reviewer of
    `apps/files/meters.py` would never see go stale.
    """

    name: str = Field(json_schema_extra=example("files.storage.bytes"))
    app: str = Field(json_schema_extra=example("files"))


class MeterPage(ListPage):
    """A page of the vocabulary, in the list envelope both doors use (ADR core-18).

    **Both doors return this class**, rather than REST returning `list[MeterOut]`
    through `@paginate` and MCP returning a hand-built twin. Two reasons, and the
    second is the one that decided it:

    * parity stops being a thing to prove and becomes a thing that is true — one
      schema, one `cursor_page` call, no `Paged...` wrapper ninja builds for one
      door and not the other (`apps/search/api.py` takes the same shape, for its
      own reason: no queryset for a paginator to slice, and there is none here
      either — the population is a registry walk);
    * `items` can carry a **declared example**. A `@paginate`d route's wrapper is
      built as `type(f"Paged{X}", (paginator.Output,), ...)`, which re-annotates
      `items` and drops any example declared on `ListPage.items` — so every
      paginated route in this tree contributes one undeclarable field to house
      rule 41's census, and `quality/rules.yaml` says so at length under
      `undeclared_example_fields` (it names the real fix, in `core.api.docs`, as
      somebody else's line). A vocabulary door that raised that ratchet to
      publish a two-field catalogue would be paying a real cost for nothing.
    """

    items: list[MeterOut] = Field(
        ...,
        json_schema_extra=example(
            [{"name": "files.storage.bytes", "app": "files"}],
        ),
    )


class UsageEntryOut(Schema):
    """One row of the ledger, as a reader of an invoice line needs it.

    `quantity` renders as a **string** on the wire, because pydantic renders a
    `Decimal` that way — which is the point: a token count or an accrual that
    round-trips through a JSON float is a number that stops adding up.

    `supersedes` and `superseded_because` travel even when empty. An audience
    that has to be able to tell "this entry is the truth" from "this entry was
    corrected" cannot do it from a field that is sometimes absent.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    meter: str
    quantity: Decimal
    occurred_at: datetime
    ref_type: str
    ref_id: UUID
    idempotency_key: str
    supersedes_id: UUID | None
    superseded_because: str
    created_at: datetime


class ThresholdCrossingOut(Schema):
    """What `usage.threshold.crossed` says: which line, in which window, and the total.

    The total is a `MeasuredOut` and not a number (ADR core-7): a subscriber that
    wants to show "you have used 1,240 of your 1,000" should not have to re-add
    the days to know what the server meant, and two subscribers re-adding them
    differently is how a dashboard and an invoice come to disagree while reading
    the same rows.

    `crossed_by` names the entry whose landing moved the total across the line —
    the causal link between an event and a row, so a subscriber can go and look.
    """

    meter: str
    period: str
    period_starts_on: date
    period_ends_on: date
    threshold: Decimal
    total: MeasuredOut
    crossed_by: UsageEntryOut


class UsageReportOut(Schema):
    """What one window of the ledger says, per meter, **with the arithmetic shown**.

    The whole of the read door's answer (ADR usage-1, § Doors). `meters` maps a
    meter name to its `MeasuredOut`, so a caller gets the total *and* the day
    subtotals it was summed from and never has to add anything up to agree with
    the server — the failure ADR core-7 exists to prevent is a dashboard, an
    export and an assistant each computing a customer's consumption differently
    from the same rows.

    **The window is on the wire and not implied.** A report that answered only
    numbers would leave a reader to work out which month "this month" was in the
    server's timezone; `period`, `starts_on` and `ends_on` say it. The window is
    UTC and half-open internally, so `ends_on` is the last day the report covers
    rather than the first day it does not — an inclusive date is what a person
    reading "1 August to 31 August" expects, and a report that said
    `2026-09-01` would be read as covering a day it does not.

    **Every quantity here is a quantity, never a price.** A meter counts things
    consumed — tokens, bytes, messages — and what any of them costs is a
    product-layer decision this app deliberately does not hold.
    """

    period: str = Field(json_schema_extra=example("month"))
    starts_on: date = Field(json_schema_extra=example("2026-08-01"))
    ends_on: date = Field(json_schema_extra=example("2026-08-31"))
    meters: dict[str, MeasuredOut] = Field(json_schema_extra=_declared_meters_example)
