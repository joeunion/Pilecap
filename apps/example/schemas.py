"""The wire shapes. Pydantic, and therefore the same shapes every door uses.

One schema language across REST, MCP tools, webhook bodies and socket payloads
is why there is no second serializer system in this repository. Schemas are
thin: shape in, shape out. No writes happen here.
"""

from __future__ import annotations

# golden: archive version move bulk history duplicate attach merge import begin
from datetime import datetime
from typing import Annotated
from uuid import UUID

from ninja import FilterLookup, FilterSchema
from pydantic import ConfigDict, Field

from apps.core.schemas import ActsOut, ActsPage, ArchivedOut, example

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: version move bulk history duplicate attach merge import begin
from apps.core.schemas import VersionedIn, VersionedOut

# golden: version move bulk history duplicate attach merge import end
# isort: split
# golden: move bulk history duplicate attach merge import begin
from apps.core.schemas import HomedOut

# golden: move bulk history duplicate attach merge import end
# isort: split
# golden: bulk history duplicate attach merge import begin
from apps.core.schemas import BulkArchiveIn, BulkMoveIn, BulkOut, BulkRestoreIn, BulkResultOut

# golden: bulk history duplicate attach merge import end
# isort: split
# golden: merge import begin
from ninja import Schema

from apps.core.schemas import EXAMPLE_VERSION

# golden: merge import end
# isort: split
# golden: attach merge import begin
from apps.tags.schemas import TagOut

# golden: attach merge import end
# isort: split
# golden: import begin
from apps.core.schemas import StrictIn

# golden: import end
# isort: split
from apps.core.schemas import ListPage, MeasuredOut


# golden: import begin
class WidgetIn(StrictIn):
    # golden: import end
    """What a client may send. `owner` and `tenant` are not on this list.

    `policy_id` is on it and `organization` is not, and the pair is the whole
    reachability story in two lines: a caller may **name** a policy (the door
    then asks `may_be_named` whether they could have reached it), and may not
    name a branch at all (the hat decides, and no answer a client sends can move
    it).
    """

    # golden: import begin
    name: str = Field(min_length=1, max_length=200, json_schema_extra=example("Bench press #4"))
    notes: str = Field(default="", json_schema_extra=example("Needs the heavy-duty mount."))
    # The id this widget has in the system it came from — what an import finds
    # it by. Optional; unique within one organization when set.
    external_ref: str = Field(default="", max_length=200, json_schema_extra=example("CRM-0042"))
    # golden: import end
    policy_id: UUID | None = None


# golden: version move bulk history duplicate attach merge import begin
class WidgetPatch(VersionedIn):
    # golden: version move bulk history duplicate attach merge import end
    """A partial update: absent means "leave it alone", not "set it to null".

    Which is also why there is no way to *clear* a policy here — `null` already
    means "leave it alone" in this grammar, and "stop being governed by this"
    is a different sentence. `update_widget` says the same thing from the other
    side.

    **`version` is required** (`VersionedIn`): the version the caller read, off
    the widget's own `version`. A save made against a version the widget no
    longer has is refused `stale_version` naming the current one, so two
    people editing at once never silently overwrite each other.
    """

    # golden: version move bulk history duplicate attach merge import begin
    name: str | None = Field(
        default=None, min_length=1, max_length=200, json_schema_extra=example("Bench press #5")
    )
    notes: str | None = Field(default=None, json_schema_extra=example("Moved to bay 3."))
    # golden: version move bulk history duplicate attach merge import end
    policy_id: UUID | None = None


# golden: archive version move bulk history duplicate attach merge import begin
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
    # golden: archive version move bulk history duplicate attach merge import end
    # The widgets that name one policy — the door an `archive_blocked` on that
    # policy points at (`route:widget-list?policy=<id>`), so the reader who was
    # refused lands on exactly the rows that held it.
    policy: Annotated[UUID | None, FilterLookup(q="policy_id")] = Field(
        default=None, json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d43")
    )


# golden: archive version move bulk history duplicate attach merge import begin
class WidgetOut(
    ArchivedOut,
    ActsOut,
    # golden: archive end
    VersionedOut,
    # golden: version end
    HomedOut,
    # golden: archive version begin
):
    # golden: archive version move bulk history duplicate attach merge import end
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

    **`archived_at` and `archived_by` come from `ArchivedOut`** and are never
    re-declared here: every archivable noun publishes one archive shape.
    **`allowed_acts` is the server's answer to "what may I press on this row"**
    — the verbs the acting hat may take on THIS row in its state (an archived
    row offers only `restore`; a member is offered no `archive`), set on the row
    by `core.verbs.with_allowed_acts` (a list page through `ActsPagination`, a
    single row at its door) and never computed by a client. It is per VIEWER,
    so it never rides an event payload. It comes from `core.schemas.ActsOut`,
    and is ALSO re-declared below, for one reason: this class published it
    first, and the wire contract's diff reads a class's own fields, so a
    re-declaration dropped before that diff reads bases would read as a removed
    field.

    **The family's three fields come from their bases too**: `version` from
    `VersionedOut` (what the next write names), `organization_name` from
    `HomedOut` (where it lives, in words — a list selects `organization`, so it
    costs no query). `owner_name` is the owner axis a move can change.
    """

    # golden: archive version move bulk history duplicate attach merge import begin
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d45"))
    name: str = Field(json_schema_extra=example("Bench press #4"))
    notes: str = Field(json_schema_extra=example("Needs the heavy-duty mount."))
    owner_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d46"))
    # `Widget.owner_email` — the property, not a traversal.
    owner_email: str = Field(json_schema_extra=example("dana@example.com"))
    tenant_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d47"))
    # Which part of the tenant's network owns this row. On the read shape
    # because a client wearing the group's hat sees rows from several branches
    # at once and has no other way to tell them apart — the slug rather than the
    # id, because the slug is what an `X-Org` header names.
    organization_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d41"))
    organization_slug: str = Field(json_schema_extra=example("northern-branch"))
    created_at: datetime = Field(json_schema_extra=example("2026-09-26T08:24:00Z"))
    updated_at: datetime = Field(json_schema_extra=example("2026-09-26T08:24:00Z"))
    allowed_acts: list[str] = Field(
        default_factory=list, json_schema_extra=example(["update", "delete", "archive"])
    )
    # golden: archive version end
    # `Widget.owner_name` — who owns it, in words, or null when the user model
    # has no name to give (the screen shows `owner_email` then).
    owner_name: str | None = Field(default=None, json_schema_extra=example("Dana Reyes"))
    # golden: move bulk history end
    # The widget this one was copied from, while it exists; null for an original.
    duplicated_from_id: UUID | None = Field(
        default=None, json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d45")
    )
    # golden: duplicate attach end
    # Set on a MERGED widget: the one it became. It still reads, read-only;
    # every change to it is refused `merged`, naming this id.
    merged_into_id: UUID | None = Field(
        default=None, json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d44")
    )
    # golden: merge end
    external_ref: str = Field(default="", json_schema_extra=example("CRM-0042"))
    # golden: import end
    # Null until the onboarding workflow's first activity marks it. It is on the
    # read shape rather than hidden behind a status endpoint because "has this
    # been onboarded yet" is the question every door gets asked about a widget.
    onboarded_at: datetime | None = Field(
        default=None, json_schema_extra=example("2026-09-26T09:00:00Z")
    )
    # The policy this widget was created under, or null. The **id** and not the
    # row: a widget at a sub-seller may be governed by a policy its own branch
    # cannot list, and embedding the row here would put on the wire exactly the
    # upward visibility `governing()` was built to avoid granting.
    policy_id: UUID | None = Field(
        default=None, json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d43")
    )


# golden: archive version move bulk history duplicate attach merge import begin
class WidgetPage(ActsPage):
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


# golden: archive version move end
#: The bulk body: one of the verbs `Widget.bulk_verbs` lists, told apart by
#: `verb`. Each member is core's own shape, so every bulk noun reads alike.
WidgetBulkIn = Annotated[BulkArchiveIn | BulkRestoreIn | BulkMoveIn, Field(discriminator="verb")]


class WidgetBulkResultOut(BulkResultOut):
    """One id's answer, its `item` narrowed to the widget it was run on."""

    item: WidgetOut | None = None


class WidgetBulkOut(BulkOut):
    """The batch's answer: one result per id, in the order the ids were sent."""

    # A list field narrowed to the noun's own result: the wire says `WidgetOut` per
    # item, which is the point, and pydantic validates the narrower type.
    results: list[WidgetBulkResultOut]  # type: ignore[assignment]  # narrowed on purpose


# golden: archive version move begin
class WidgetDetailOut(WidgetOut):
    """One widget, as its detail door answers it: the row and the words on it.

    A widget that takes tags (`Widget.attachments`) answers them HERE — on the
    record — and nowhere else: a list's row is `WidgetOut`, and an event's
    payload is the row, never what one reader sees attached to it. `tags` are
    the words on this widget as the reader's hat sees them, archived words
    included (the link stands; the word is read-only).
    """

    # golden: archive version move bulk history duplicate end
    tags: list[TagOut] = Field(
        default_factory=list,
        json_schema_extra=example(
            [
                {
                    "id": "0196a1f2-7c2d-7e41-9b3a-5d6e7f8a9b0c",
                    "name": "Urgent",
                    "slug": "urgent",
                    "tenant_id": "0196a1f2-0000-7000-8000-000000000001",
                    "created_at": "2026-09-27T08:24:00Z",
                    "updated_at": "2026-09-27T08:24:00Z",
                    "archived_at": None,
                    "archived_by": None,
                }
            ]
        ),
    )
    # golden: archive version move bulk history duplicate begin


# golden: archive version move bulk history duplicate attach end
class WidgetMergeIn(VersionedIn):
    """Fold this widget into another: the one it becomes, and both versions read.

    `version` is the version of the widget in the path — the one that goes —
    and `into_version` the survivor's: a merge edits both, so both must be the
    versions the person was looking at when they confirmed it.
    """

    into_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d44"))
    into_version: int = Field(json_schema_extra=example(EXAMPLE_VERSION))


class RepointOut(Schema):
    """What one owning app moves across in a merge: its words, and how many."""

    title: str = Field(json_schema_extra=example("Notes"))
    left: int = Field(json_schema_extra=example(3))


class WidgetMergePreviewOut(Schema):
    """What a merge WOULD move, per owning app — read before anything is written."""

    loser_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d45"))
    into_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d44"))
    repoints: list[RepointOut] = Field(
        json_schema_extra=example([{"title": "Notes", "left": 3}, {"title": "Tags", "left": 1}])
    )


# golden: merge import end
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


class WidgetPolicyOut(ArchivedOut):
    """What a client gets back for a policy.

    `organization_slug` is on it for the same reason it is on `WidgetOut` — a
    caller wearing the group's hat lists policies from several branches at once
    — and here it does a second job: it is how a caller can tell that the policy
    **governing** them was set one or more levels up. The resolution answers
    with the row; the slug says whose row it is.

    An archivable noun's answer, so `archived_at` and `archived_by` come from
    `ArchivedOut`: an archived policy reads the same as a widget does.
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
