"""The wire shapes. Pydantic, and therefore the same shapes every door uses."""

from __future__ import annotations

# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
from datetime import datetime
from typing import Annotated
from uuid import UUID

from ninja import FilterLookup, FilterSchema
from pydantic import ConfigDict, Field

from pilecap import ActsOut, ActsPage, ArchivedOut, example, personal

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: version move bulk history duplicate attach merge import begin
from pilecap import VersionedIn, VersionedOut

# golden: noun end

# golden: version move bulk history duplicate attach merge import end
# isort: split
# golden: move bulk history duplicate attach merge import begin
from pilecap import HomedOut

# golden: move bulk history duplicate attach merge import end
# isort: split
# golden: bulk history duplicate attach merge import begin
from pilecap import BulkArchiveIn, BulkMoveIn, BulkOut, BulkRestoreIn, BulkResultOut

# golden: bulk history duplicate attach merge import end
# isort: split
# golden: merge import begin
from pilecap import EXAMPLE_VERSION, RepointOut

# golden: merge import end
# isort: split
# golden: attach merge import begin
from pilecap.attach import DjbTagOut

# golden: attach merge import end
# isort: split
# golden: import begin
# golden: noun begin
from pilecap import StrictIn

# golden: import end
# isort: split
from pydantic import AwareDatetime

# golden: noun end
# golden: policy begin
# golden: child entry begin
from pilecap import ListPage

# golden: policy end
# golden: child entry end

# isort: split
# golden: stat count begin
# golden: merge import begin
# golden: child entry begin
from ninja import Schema

# golden: merge import end
# golden: child entry end
from pilecap import MeasuredOut

# golden: stat count end
# isort: split
# golden: child entry begin
from apps.example.models import WidgetEntry

# golden: child entry end


# golden: import begin
# golden: noun begin
class WidgetIn(StrictIn):
    # golden: noun end
    # golden: import end
    """What a client may send. `owner` and `tenant` are not on this list."""

    # golden: import begin
    # golden: noun begin
    name: str = Field(min_length=1, max_length=200, json_schema_extra=example("Bench press #4"))
    notes: str = Field(default="", json_schema_extra=example("Needs the heavy-duty mount."))
    # golden: noun end
    # The id this widget has in the system it came from.
    external_ref: str = Field(default="", max_length=200, json_schema_extra=example("CRM-0042"))
    # golden: import end
    # golden: policy begin
    policy_id: UUID | None = Field(
        default=None, json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d43")
    )
    # golden: policy end
    # golden: noun begin
    # golden: field due_at begin
    # Timezone-aware or refused: a moment with no offset is somebody's assumption.
    due_at: AwareDatetime | None = Field(
        default=None, json_schema_extra=example("2026-11-02T17:00:00Z")
    )
    # golden: field due_at end


# golden: version move bulk history duplicate attach merge import begin
class WidgetPatch(VersionedIn):
    # golden: noun end
    # golden: version move bulk history duplicate attach merge import end
    """A partial update: absent means "leave it alone", not "set it to null"."""

    # golden: version move bulk history duplicate attach merge import begin
    # golden: noun begin
    name: str | None = Field(
        default=None, min_length=1, max_length=200, json_schema_extra=example("Bench press #5")
    )
    notes: str | None = Field(default=None, json_schema_extra=example("Moved to bay 3."))
    # golden: noun end
    # golden: version move bulk history duplicate attach merge import end
    # golden: policy begin
    policy_id: UUID | None = Field(
        default=None, json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d43")
    )
    # golden: policy end
    # golden: noun begin
    # golden: field due_at begin
    # `null` leaves it alone, as everywhere in this grammar; `clear_due_at` removes it.
    due_at: AwareDatetime | None = Field(
        default=None, json_schema_extra=example("2026-12-01T09:30:00Z")
    )
    clear_due_at: bool | None = Field(default=None, json_schema_extra=example(False))
    # golden: field due_at end


# golden: archive version move bulk history duplicate attach merge import begin
class WidgetFilter(FilterSchema):
    """The narrowings a client may ask for, declared rather than improvised."""

    # golden: filter name begin
    name: Annotated[str | None, FilterLookup(q="name__icontains")] = Field(
        default=None, json_schema_extra=example("bench")
    )
    # golden: filter name end
    # golden: noun end
    # golden: archive version move bulk history duplicate attach merge import end
    # golden: policy begin
    # The widgets that name one policy: the door an `archive_blocked` points at.
    policy: Annotated[UUID | None, FilterLookup(q="policy_id")] = Field(
        default=None, json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d43")
    )
    # golden: policy end
    # golden: noun begin
    # Strictly before and strictly after; a widget with no due date matches neither.
    due_before: Annotated[AwareDatetime | None, FilterLookup(q="due_at__lt")] = Field(
        default=None, json_schema_extra=example("2026-11-01T00:00:00Z")
    )
    due_after: Annotated[AwareDatetime | None, FilterLookup(q="due_at__gt")] = Field(
        default=None, json_schema_extra=example("2026-10-01T00:00:00Z")
    )


# golden: archive version move bulk history duplicate attach merge import begin
class WidgetOut(
    ArchivedOut,
    ActsOut,
    # golden: archive end
    VersionedOut,
    # golden: noun end
    # golden: version end
    HomedOut,
    # golden: archive version begin
    # golden: noun begin
):
    # golden: noun end
    # golden: archive version move bulk history duplicate attach merge import end
    """What a client gets back."""

    # golden: archive version move bulk history duplicate attach merge import begin
    # golden: noun begin
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d45"))
    name: str = Field(json_schema_extra=example("Bench press #4"))
    notes: str = Field(json_schema_extra=example("Needs the heavy-duty mount."))
    owner_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d46"))
    # `Widget.owner_email` — the property, not a traversal.
    # golden: a person's field is personal() — the doors answer it, an event never carries it.
    owner_email: str = Field(json_schema_extra=personal(example("dana@example.com")))
    tenant_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d47"))
    # Which part of the tenant's network owns this row.
    organization_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d41"))
    organization_slug: str = Field(json_schema_extra=example("northern-branch"))
    created_at: datetime = Field(json_schema_extra=example("2026-09-26T08:24:00Z"))
    updated_at: datetime = Field(json_schema_extra=example("2026-09-26T08:24:00Z"))
    allowed_acts: list[str] = Field(
        default_factory=list, json_schema_extra=example(["update", "delete", "archive"])
    )
    # golden: noun end
    # golden: archive version end
    # `Widget.owner_name`: who owns it, in words, or null when the user has no name.
    owner_name: str | None = Field(default=None, json_schema_extra=personal(example("Dana Reyes")))
    # golden: move bulk history end
    # The widget this one was copied from, while it exists; null for an original.
    duplicated_from_id: UUID | None = Field(
        default=None, json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d45")
    )
    # golden: duplicate attach end
    # Set on a MERGED widget: the one it became.
    merged_into_id: UUID | None = Field(
        default=None, json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d44")
    )
    # golden: merge end
    external_ref: str = Field(default="", json_schema_extra=example("CRM-0042"))
    # golden: import end
    # golden: workflow onboard begin
    # Null until the onboarding workflow's first activity marks it.
    onboarded_at: datetime | None = Field(
        default=None, json_schema_extra=example("2026-09-26T09:00:00Z")
    )
    # golden: workflow onboard end
    # golden: noun begin
    # golden: field due_at begin
    due_at: datetime | None = Field(default=None, json_schema_extra=example("2026-11-02T17:00:00Z"))
    # golden: field due_at end
    # golden: noun end
    # golden: enum status begin
    status: str = Field(json_schema_extra=example("active"))
    # golden: enum status end
    # golden: policy begin
    # The policy this widget was created under, or null; the id, never the row.
    policy_id: UUID | None = Field(
        default=None, json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d43")
    )
    # golden: policy end


# golden: enum status begin
class WidgetTransitionIn(StrictIn):
    """The status a widget moves to: one step along its chain from where it is."""

    status: str = Field(json_schema_extra=example("active"))


# golden: enum status end
# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
class WidgetPage(ActsPage):
    """A page of widgets — the list envelope, for a door that has no query string."""

    items: list[WidgetOut]


# golden: noun end


# golden: archive version end
class WidgetMovedOut(WidgetOut):
    """The `moved` event's payload: the row where it now is, and the node it left."""

    from_organization_id: UUID


# golden: move end
#: The bulk body: one of the verbs `Widget.bulk_verbs` lists, told apart by `verb`.
WidgetBulkIn = Annotated[BulkArchiveIn | BulkRestoreIn | BulkMoveIn, Field(discriminator="verb")]


class WidgetBulkResultOut(BulkResultOut):
    """One id's answer, its `item` narrowed to the widget it was run on."""

    item: WidgetOut | None = None


class WidgetBulkOut(BulkOut):
    """The batch's answer: one result per id, in the order the ids were sent."""

    # A list field narrowed to the noun's own result.
    results: list[WidgetBulkResultOut]  # type: ignore[assignment]  # narrowed on purpose


# golden: archive version move begin
# golden: noun begin
class WidgetDetailOut(WidgetOut):
    """One widget, as its detail door answers it: the row and the words on it."""

    # golden: noun end

    # golden: archive version move bulk history duplicate end
    tags: list[DjbTagOut] = Field(
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
    """Fold this widget into another: the one it becomes, and both versions read."""

    into_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d44"))
    into_version: int = Field(json_schema_extra=example(EXAMPLE_VERSION))


class WidgetMergePreviewOut(Schema):
    """What a merge WOULD move, per owning app — read before anything is written."""

    loser_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d45"))
    into_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d44"))
    repoints: list[RepointOut] = Field(
        json_schema_extra=example([{"title": "Notes", "left": 3}, {"title": "Tags", "left": 1}])
    )


class WidgetMergedOut(WidgetOut):
    """The `merged` event's payload: the survivor, the loser folded in, and what moved across."""

    loser_id: UUID
    repoints: list[RepointOut]


# golden: merge import end
# golden: workflow onboard begin
class WidgetOnboardedOut(WidgetOut):
    """The `onboarded` event's payload: the row, and whether anybody approved in time."""

    approved: bool


# golden: workflow onboard end


# golden: policy begin
class WidgetPolicyIn(StrictIn):
    """What a client may send to set a policy."""

    name: str = Field(min_length=1, max_length=200, json_schema_extra=example("Heavy equipment"))
    body: str = Field(
        default="", json_schema_extra=example("Anything over 50kg needs two approvals.")
    )


class WidgetPolicyOut(ArchivedOut):
    """What a client gets back for a policy."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d43"))
    name: str = Field(json_schema_extra=example("Heavy equipment"))
    body: str = Field(json_schema_extra=example("Anything over 50kg needs two approvals."))
    tenant_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d47"))
    organization_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d41"))
    # `WidgetPolicy.organization_slug`: the property, not a traversal (ADR example-3).
    organization_slug: str = Field(json_schema_extra=example("northern-branch"))
    created_at: datetime = Field(json_schema_extra=example("2026-09-26T08:24:00Z"))
    updated_at: datetime = Field(json_schema_extra=example("2026-09-26T08:24:00Z"))


class WidgetPolicyPage(ListPage):
    """A page of policies — the same envelope `@paginate` gives the REST list."""

    items: list[WidgetPolicyOut]


# golden: policy end
# golden: child entry begin
class WidgetEntryIn(StrictIn):
    """One line to append to a widget's ledger."""

    widget_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d45"))
    kind: str = Field(default="note", json_schema_extra=example(WidgetEntry.Kind.NOTE.value))
    note: str = Field(default="", json_schema_extra=example("Checked and signed off."))
    organization_slug: str | None = Field(
        default=None, json_schema_extra=example("northern-branch")
    )


class WidgetEntryOut(Schema):
    """One ledger line, as every door renders it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d50"))
    widget_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d45"))
    kind: str = Field(json_schema_extra=example(WidgetEntry.Kind.NOTE.value))
    note: str = Field(json_schema_extra=example("Checked and signed off."))
    tenant_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d47"))
    organization_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d41"))
    organization_slug: str = Field(json_schema_extra=example("northern-branch"))
    created_at: datetime = Field(json_schema_extra=example("2026-09-26T08:24:00Z"))


class WidgetEntryPage(ListPage):
    """A page of ledger lines — the list envelope, for the door with no query string."""

    items: list[WidgetEntryOut]


# golden: child entry end
# golden: stat count begin
class WidgetStatsOut(Schema):
    """The widget count for the acting hat, **with the arithmetic attached**."""

    count: MeasuredOut
    # golden: stat count end
