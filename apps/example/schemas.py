"""The wire shapes. Pydantic, and therefore the same shapes every door uses.

One schema language across REST, MCP tools, webhook bodies and socket payloads
is why there is no second serializer system in this repository. Schemas are
thin: shape in, shape out. No writes happen here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from ninja import FilterLookup, FilterSchema, Schema
from pydantic import ConfigDict, Field

from apps.core.schemas import ListPage, MeasuredOut, StrictIn, example


class WidgetIn(StrictIn):
    """What a client may send. `owner` and `tenant` are not on this list.

    `policy_id` is on it and `organization` is not, and the pair is the whole
    reachability story in two lines: a caller may **name** a policy (the door
    then asks `may_be_named` whether they could have reached it), and may not
    name a branch at all (the hat decides, and no answer a client sends can move
    it).
    """

    name: str = Field(min_length=1, max_length=200, json_schema_extra=example("Bench press #4"))
    notes: str = Field(default="", json_schema_extra=example("Needs the heavy-duty mount."))
    policy_id: UUID | None = None


class WidgetPatch(StrictIn):
    """A partial update: absent means "leave it alone", not "set it to null".

    Which is also why there is no way to *clear* a policy here — `null` already
    means "leave it alone" in this grammar, and "stop being governed by this"
    is a different sentence. `update_widget` says the same thing from the other
    side.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = None
    policy_id: UUID | None = None


class WidgetFilter(FilterSchema):
    """The narrowings a client may ask for, declared rather than improvised.

    A `FilterSchema` is how ninja turns query parameters into a `Q` without any
    route reading `request.GET` — which is where filtering usually goes wrong,
    because a hand-rolled filter reaches straight into `.filter(**request.GET)`
    and lets a client query any column and traverse any relation.

    `name` is `icontains` here rather than exact, because "find the widget I
    half-remember the name of" is what a client actually wants; exact matching
    is what the detail route by id is for.
    """

    name: Annotated[str | None, FilterLookup(q="name__icontains")] = None


class WidgetOut(Schema):
    """What a client gets back.

    `owner_email` is resolved from the related row, which is why every list
    selects `owner`; it is also the field that would turn into an N+1 the day
    somebody removes the `select_related`, and the query pin in the tests is
    what makes that a failure rather than a slow page.

    **Nothing here carries a `Field(alias=...)`, and that is a rule rather than
    an accident.** An alias is a *name*, and the doors do not agree on which
    name to put on the wire: REST renders by field name, the MCP transport
    renders `structuredContent` by alias. `owner_email = Field(alias=
    "owner.email")` therefore made the machine door answer `owner.email` — same
    row, same values, two key sets (ADR example-3). A relation is
    walked by a **property on the model** instead: a real attribute, which
    `from_attributes` finds under one name, so both doors say the same thing.
    `apps/example/tests/test_doors_over_the_wire.py` compares the two wire
    shapes key-for-key and is what keeps this true.

    **The break this cost, stated rather than discovered:** an MCP client that
    had learned to read `owner.email` and `organization.slug` off
    `structuredContent` now reads `owner_email` and `organization_slug`. That
    was accepted when the aliases came out (ADR example-3) because REST is the
    contract and the machine door was the one saying something REST never said.
    Nothing on the REST wire moved — the same bytes before and after.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str = Field(json_schema_extra=example("Bench press #4"))
    notes: str = Field(json_schema_extra=example("Needs the heavy-duty mount."))
    owner_id: UUID
    # `Widget.owner_email` — the property, not a traversal.
    owner_email: str = Field(json_schema_extra=example("dana@example.com"))
    tenant_id: UUID
    # Which part of the tenant's network owns this row. On the read shape
    # because a client wearing the group's hat sees rows from several branches
    # at once and has no other way to tell them apart — the slug rather than the
    # id, because the slug is what an `X-Org` header names.
    organization_id: UUID
    organization_slug: str = Field(json_schema_extra=example("northern-branch"))
    created_at: datetime
    updated_at: datetime
    # Null until the onboarding workflow's first activity marks it. It is on the
    # read shape rather than hidden behind a status endpoint because "has this
    # been onboarded yet" is the question every door gets asked about a widget.
    onboarded_at: datetime | None = None
    # The policy this widget was created under, or null. The **id** and not the
    # row: a widget at a sub-seller may be governed by a policy its own branch
    # cannot list, and embedding the row here would put on the wire exactly the
    # upward visibility `governing()` was built to avoid granting.
    policy_id: UUID | None = None


class WidgetPage(ListPage):
    """A page of widgets — the list envelope, for a door that has no query string.

    REST gets this shape from ninja's `@paginate` — `{"items": [...],
    "has_more": ..., "next_cursor": ...}` — and never has to name it. The MCP
    tool returns a value rather than a response, so the same envelope has to be
    a schema it can declare — and it is
    deliberately the *same* envelope, because a machine client that has learned
    to unwrap the REST list should not have to learn a second shape for the
    machine door.
    """

    items: list[WidgetOut]


class WidgetPolicyIn(StrictIn):
    """What a client may send to set a policy.

    There is no `organization` on this list, and its absence is the enforcement:
    a policy lands at the hat the request was made under, exactly as a widget
    does. A caller that could name a branch could set config for a branch it
    holds no membership over — and config, unlike a row, is obeyed by
    everything underneath it.
    """

    name: str = Field(min_length=1, max_length=200, json_schema_extra=example("Heavy equipment"))
    body: str = Field(
        default="", json_schema_extra=example("Anything over 50kg needs two approvals.")
    )


class WidgetPolicyOut(Schema):
    """What a client gets back for a policy.

    `organization_slug` is on it for the same reason it is on `WidgetOut` — a
    caller wearing the group's hat lists policies from several branches at once
    — and here it does a second job: it is how a caller can tell that the policy
    **governing** them was set one or more levels up. The resolution answers
    with the row; the slug says whose row it is.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str = Field(json_schema_extra=example("Heavy equipment"))
    body: str = Field(json_schema_extra=example("Anything over 50kg needs two approvals."))
    tenant_id: UUID
    organization_id: UUID
    # `WidgetPolicy.organization_slug` — the property, not a traversal (ADR
    # example-3: an alias is a name, and the two doors do not agree on names).
    organization_slug: str = Field(json_schema_extra=example("northern-branch"))
    created_at: datetime
    updated_at: datetime


class WidgetPolicyPage(ListPage):
    """A page of policies — the same envelope `@paginate` gives the REST list."""

    items: list[WidgetPolicyOut]


class WidgetEntryIn(StrictIn):
    """One line to append to a widget's ledger.

    `organization_slug` is **optional and inert by construction**, and it is on
    this shape deliberately rather than by accident. An entry takes its
    organization from its widget (`WidgetEntry.derive_org_from`), so the only
    value the landing gate will accept is the one it would have derived anyway:
    naming the widget's own branch changes nothing, and naming any other branch
    is refused field-by-field on `organization`. It is here so that the gate is
    a *live* refusal on the wire rather than a model invariant nobody can reach
    — the thing that would otherwise be true only until somebody wrote a service
    that stamped the actor's hat on it.
    """

    widget_id: UUID
    kind: str = Field(default="note", json_schema_extra=example("inspection"))
    note: str = Field(default="", json_schema_extra=example("Checked and signed off."))
    organization_slug: str | None = Field(
        default=None, json_schema_extra=example("northern-branch")
    )


class WidgetEntryOut(Schema):
    """One ledger line, as every door renders it.

    There is no `WidgetEntryPatch` and there will not be one: the model is
    `append_only`, so there is nothing to send.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    widget_id: UUID
    kind: str = Field(json_schema_extra=example("inspection"))
    note: str = Field(json_schema_extra=example("Checked and signed off."))
    tenant_id: UUID
    organization_id: UUID
    organization_slug: str = Field(json_schema_extra=example("northern-branch"))
    created_at: datetime


class WidgetEntryPage(ListPage):
    """A page of ledger lines — the list envelope, for the door with no query string."""

    items: list[WidgetEntryOut]


class WidgetStatsOut(Schema):
    """The widget count for the acting hat, **with the arithmetic attached**.

    One field, and it is a `MeasuredOut` rather than an `int` (ADR core-7): a
    number a door computed travels with the formula and the inputs it was
    computed from, so a screen, an export and an assistant cannot come to
    disagree about it while all three read the same rows. `count` here is
    `onboarded + pending`, and both terms are on the wire — a client can check
    the arithmetic without a second request and without a second
    implementation, which is the whole contract.

    A second aggregate would be a second `MeasuredOut` beside this one, not a
    naked number added to it. That is the convention this schema exists to
    demonstrate; enforcing it is criteria-tier and honestly so, because "any
    endpoint returning a computed aggregate" is an open set.
    """

    count: MeasuredOut
