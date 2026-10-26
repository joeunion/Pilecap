"""The example API: one capability function per door pair, a thin route over each (ADR api-1)."""

# No `from __future__ import annotations`: ninja resolves schema-typed query parameters at import.

# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
from uuid import UUID

from django.db.models import QuerySet
from ninja import Query, Router
from ninja.pagination import paginate

from apps.example.models import Widget
from apps.example.schemas import WidgetDetailOut, WidgetFilter, WidgetOut
from apps.example.selectors import get_widget, list_widgets
from apps.example.services import archive_widget, restore_widget
from pilecap import Actor, NotFound, Show, may_be_named, road, with_allowed_acts
from pilecap.api import (
    API_AUTH,
    ActsPagination,
    Tag,
    TenantRequest,
    acting,
    also_refuses,
    ordered_by,
    searched,
)
from pilecap.tenancy import Tenant

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: version move bulk history duplicate attach merge import begin
from typing import Any

from apps.example.schemas import WidgetPatch
from apps.example.services import update_widget
from pilecap import AuditEntry, HistoryEntryOut
from pilecap.api import CursorPagination
from pilecap.tenancy import list_history

# golden: noun end

# golden: version move bulk history duplicate attach merge import end
# isort: split
# golden: move bulk history duplicate attach merge import begin
from apps.example.services import move_widget
from pilecap import VersionedMoveIn
from pilecap.tenancy import Organization, get_organization

# golden: move bulk history duplicate attach merge import end
# isort: split
# golden: bulk history duplicate attach merge import begin
from collections.abc import Callable
from typing import cast

from apps.example.schemas import WidgetBulkIn, WidgetBulkOut, WidgetBulkResultOut
from pilecap import ROADS, BulkRefusalOut, Invalid, resolve_subject, run_bulk

# golden: bulk history duplicate attach merge import end
# isort: split
# golden: duplicate attach merge import begin
# golden: noun begin
from ninja import Status

# golden: noun end
# isort: split
from apps.example.services import duplicate_widget
from pilecap import IDEMPOTENCY_KEY_HEADER

# golden: duplicate attach merge import end
# isort: split
# golden: merge import begin
from apps.example.schemas import WidgetMergeIn, WidgetMergePreviewOut
from apps.example.selectors import get_widget_merge_preview
from apps.example.services import merge_widget
from pilecap import RepointOut

# golden: merge import end
# isort: split
# golden: attach merge import begin
from apps.example.selectors import list_widget_tags

# golden: attach merge import end
# isort: split
# golden: import begin
# golden: noun begin
from apps.example.schemas import WidgetIn
from apps.example.services import create_widget

# golden: import end
# isort: split
from datetime import datetime

# golden: noun end
# golden: noun begin
from django.db.models import BooleanField, ExpressionWrapper, Q

# golden: noun end
# isort: split
# golden: child entry begin
from apps.example.models import WidgetEntry
from apps.example.schemas import WidgetEntryIn, WidgetEntryOut
from apps.example.selectors import list_widget_entries
from apps.example.services import record_widget_entry

# golden: child entry end
# isort: split
# golden: noun begin
from apps.example.services import delete_widget

# golden: noun end
# isort: split
# golden: workflow onboard begin
from apps.example.services import approve_widget

# golden: workflow onboard end
# isort: split
# golden: policy begin
from apps.example.models import WidgetPolicy
from apps.example.schemas import WidgetPolicyIn, WidgetPolicyOut
from apps.example.selectors import (
    get_governing_widget_policy,
    get_widget_policy,
    list_widget_policies,
)
from apps.example.services import (
    archive_widget_policy,
    create_widget_policy,
    restore_widget_policy,
)
from pilecap.api import refuses

# golden: policy end
# isort: split
# golden: verb touch begin
from apps.example.services import touch_widget

# golden: verb touch end
# isort: split
# golden: enum status begin
from apps.example.schemas import WidgetTransitionIn
from apps.example.services import transition_widget

# golden: enum status end
# isort: split
# golden: stat count begin
from decimal import Decimal

from apps.example.schemas import WidgetStatsOut
from pilecap import MeasuredBasisOut, MeasuredOut

# golden: stat count end
# golden: noun begin
# golden: archive version move bulk history duplicate attach merge import begin
#: The path segment `config.api` mounts this router under.
PREFIX = "widgets"

#: What `?ordering=` may name — a column allow-list, never a relation.
ORDERING: tuple[str, ...] = ("created_at", "updated_at", "name")
# golden: archive version move bulk history duplicate attach merge import end
# golden: ordering due_at begin
ORDERING += ("due_at",)
# golden: ordering due_at end
# golden: archive version move bulk history duplicate attach merge import begin

#: What `?q=` searches: this row's text columns, never a related table's.
SEARCH_FIELDS = ("name", "notes")

#: This app's tag, collected into the OpenAPI document's `tags` section (ADR api-1).
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

router = Router(tags=["widgets"], auth=API_AUTH)


@road(
    "widget_list",
    example="apps/example/tests/test_doors_over_the_wire.py::test_both_doors_refuse_the_same_withheld_read_with_the_same_words",
)
def widget_list(
    *,
    tenant: Tenant,
    actor: Actor,
    filters: WidgetFilter,
    q: str | None = None,
    ordering: str = "-created_at",
    show: Show = "live",
) -> QuerySet[Widget]:
    """The widgets this hat may see, narrowed, searched and ordered as allowed."""
    # authz: `list_widgets` asks `widget.read` at the hat.
    widgets: QuerySet[Widget] = filters.filter(
        list_widgets(tenant=tenant, org=actor.org, actor=actor, show=show)
    )
    widgets = searched(widgets, q, fields=SEARCH_FIELDS)
    widgets = ordered_by(widgets, ordering, allowed=ORDERING, default="-created_at")
    # golden: archive version move bulk history duplicate attach merge import end
    widgets = undated_last(widgets)
    # golden: archive version move bulk history duplicate attach merge import begin
    return widgets


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

    List widgets, newest first; without the read, `403 forbidden`: ask an administrator.
    """
    actor, tenant = acting(request)
    return widget_list(
        tenant=tenant, actor=actor, filters=filters, q=q, ordering=ordering, show=show
    )


# golden: archive version move bulk history duplicate attach merge import end
def undated_last(widgets: QuerySet[Widget]) -> QuerySet[Widget]:
    """A list led by `due_at` keeps the undated widgets last, in either direction."""
    leading = next(iter(widgets.query.order_by), None)
    if not isinstance(leading, str) or leading.removeprefix("-") != "due_at":
        return widgets
    undated = ExpressionWrapper(Q(due_at__isnull=True), output_field=BooleanField())
    return widgets.annotate(undated=undated).order_by("undated", *widgets.query.order_by)


# golden: noun end


# golden: verb touch begin
@road(
    "widget_touch",
    example="apps/example/tests/test_doors_over_the_wire.py::test_a_touch_is_one_body_on_rest_mcp_and_the_outbox",
)
def widget_touch(*, tenant: Tenant, actor: Actor, widget_id: UUID) -> WidgetOut:
    """Mark one widget this hat reaches as seen now."""
    # authz: `touch_widget` asks `widget.update` at the row's node.
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    touched = touch_widget(tenant=tenant, actor=actor, widget=widget)
    return WidgetOut.from_orm(with_allowed_acts([touched], actor)[0])


@router.post("/{widget_id}/touch/", response=WidgetOut, url_name="widget-touch")
@also_refuses("archived")
# golden: verb touch end
@also_refuses("merged")
# golden: verb touch begin
def touch_widget_route(request: TenantRequest, widget_id: UUID) -> WidgetOut:
    """Touch a widget

    Mark one widget as seen now. Takes no body; only its `updated_at` moves.
    """
    actor, tenant = acting(request)
    return widget_touch(tenant=tenant, actor=actor, widget_id=widget_id)


# golden: verb touch end
# golden: enum status begin
@road(
    "widget_transition",
    example="apps/example/tests/test_doors_over_the_wire.py::test_a_transition_is_one_body_on_rest_mcp_and_the_outbox",
)
def widget_transition(*, tenant: Tenant, actor: Actor, widget_id: UUID, status: str) -> WidgetOut:
    """Move one widget this hat reaches to the next status."""
    # authz: `transition_widget` asks `widget.update` at the row's node.
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    moved = transition_widget(tenant=tenant, actor=actor, widget=widget, status=status)
    return WidgetOut.from_orm(with_allowed_acts([moved], actor)[0])


@router.post("/{widget_id}/transition/", response=WidgetOut, url_name="widget-transition")
@also_refuses("archived", "conflict", "invalid")
# golden: enum status end
@also_refuses("merged")
# golden: enum status begin
def transition_widget_route(
    request: TenantRequest, widget_id: UUID, payload: WidgetTransitionIn
) -> WidgetOut:
    """Move a widget's status

    Send the `status` the widget moves to: the one step forward from the one it has.
    """
    actor, tenant = acting(request)
    return widget_transition(tenant=tenant, actor=actor, widget_id=widget_id, status=payload.status)


# golden: enum status end


# golden: policy begin
def resolve_named_policy(
    *, tenant: Tenant, actor: Actor, policy_id: UUID | None
) -> WidgetPolicy | None:
    """The policy an id names on the hat's ancestor chain, or `None`; the caller asks reach."""
    if policy_id is None:
        return None
    return get_governing_widget_policy(
        tenant=tenant, org=actor.org, policy_id=policy_id, actor=actor
    )


# golden: policy end
# golden: import begin
# golden: noun begin
@road(
    "widget_create",
    example="apps/example/tests/test_mcp.py::test_create_widget_writes_the_row_and_owns_it",
)
def widget_create(
    *,
    tenant: Tenant,
    actor: Actor,
    name: str,
    notes: str = "",
    # golden: noun end
    external_ref: str = "",
    # golden: import end
    # golden: policy begin
    policy_id: UUID | None = None,
    # golden: policy end
    # golden: noun begin
    # golden: field due_at begin
    due_at: datetime | None = None,
    # golden: field due_at end
    # golden: import begin
) -> WidgetOut:
    """Create a widget at the acting hat."""
    # golden: noun end
    # golden: import end
    # golden: policy begin
    policy = resolve_named_policy(tenant=tenant, actor=actor, policy_id=policy_id)
    if policy is not None and not may_be_named(actor, policy):
        raise NotFound()
    # golden: policy end
    # golden: import begin
    # golden: noun begin
    widget = create_widget(
        tenant=tenant,
        actor=actor,
        name=name,
        notes=notes,
        # golden: noun end
        external_ref=external_ref,
        # golden: import end
        # golden: policy begin
        policy=policy,
        # golden: policy end
        # golden: noun begin
        # golden: field due_at begin
        due_at=due_at,
        # golden: field due_at end
        # golden: import begin
    )
    return WidgetOut.from_orm(with_allowed_acts([widget], actor)[0])


@router.post("/", response={201: WidgetOut}, url_name="widget-create")
def create_widget_route(request: TenantRequest, payload: WidgetIn) -> Status[WidgetOut]:
    """Create a widget

    Create a widget.
    """
    actor, tenant = acting(request)
    created = widget_create(
        tenant=tenant,
        actor=actor,
        name=payload.name,
        notes=payload.notes,
        # golden: noun end
        external_ref=payload.external_ref,
        # golden: import end
        # golden: policy begin
        policy_id=payload.policy_id,
        # golden: policy end
        # golden: noun begin
        # golden: field due_at begin
        due_at=payload.due_at,
        # golden: field due_at end
        # golden: import begin
    )
    return Status(201, created)
    # golden: noun end


# golden: import end


# golden: stat count begin
@road(
    "widget_stats",
    example="apps/example/tests/test_doors_over_the_wire.py::test_the_two_doors_agree_on_a_measured_number_and_its_basis",
)
def widget_stats(*, tenant: Tenant, actor: Actor) -> WidgetStatsOut:
    """The measured widget count for one hat, `live + archived` with both terms (ADR core-7)."""
    # authz: `list_widgets` asks `widget.read` at the hat; asking here too would be a second copy.
    visible = list_widgets(tenant=tenant, org=actor.org, actor=actor, show="all")
    live = visible.filter(archived_at__isnull=True).count()
    archived = visible.filter(archived_at__isnull=False).count()
    return WidgetStatsOut(
        count=MeasuredOut(
            value=Decimal(live + archived),
            basis=MeasuredBasisOut(
                formula="live + archived",
                inputs={"live": Decimal(live), "archived": Decimal(archived)},
            ),
        )
    )


@router.get("/stats/", response=WidgetStatsOut, url_name="widget_stats-detail")
def widget_stats_route(request: TenantRequest) -> WidgetStatsOut:
    """Retrieve widget statistics

    How many widgets you see; without the read, `403 forbidden`: ask an administrator.
    """
    actor, tenant = acting(request)
    return widget_stats(tenant=tenant, actor=actor)


# golden: stat count end


# golden: policy begin
@road(
    "widget_policies_list",
    example="apps/example/tests/test_network.py::test_a_seller_lists_its_own_and_its_sub_sellers_policies",
)
def widget_policies_list(
    *, tenant: Tenant, actor: Actor, show: Show = "live"
) -> QuerySet[WidgetPolicy]:
    """The policies the acting hat owns — downward only, never the one governing it (ADR core-3)."""
    # authz: `list_widget_policies` asks `widget_policy.read` at the hat.
    policies: QuerySet[WidgetPolicy] = list_widget_policies(
        tenant=tenant, org=actor.org, actor=actor, show=show
    )
    return policies


@router.get("/policies/", response=list[WidgetPolicyOut], url_name="widget_policies-list")
@paginate(CursorPagination)
def list_widget_policies_route(
    request: TenantRequest, show: Show = "live"
) -> QuerySet[WidgetPolicy]:
    """List widget policies

    List widget policies; without the read, `403 forbidden`: ask an administrator.
    """
    actor, tenant = acting(request)
    return widget_policies_list(tenant=tenant, actor=actor, show=show)


@road(
    "widget_policy_create",
    example="apps/example/tests/test_network.py::test_setting_a_policy_needs_a_role_and_lands_on_the_acting_hat",
)
def widget_policy_create(
    *, tenant: Tenant, actor: Actor, name: str, body: str = ""
) -> WidgetPolicyOut:
    """Set a widget policy on the acting hat."""
    return WidgetPolicyOut.from_orm(
        create_widget_policy(tenant=tenant, actor=actor, name=name, body=body)
    )


@router.post("/policies/", response={201: WidgetPolicyOut}, url_name="widget_policy-create")
def create_widget_policy_route(
    request: TenantRequest, payload: WidgetPolicyIn
) -> Status[WidgetPolicyOut]:
    """Create a widget policy

    Create a widget policy on your acting organization.
    """
    actor, tenant = acting(request)
    return Status(
        201, widget_policy_create(tenant=tenant, actor=actor, name=payload.name, body=payload.body)
    )


@road(
    "governing_widget_policy_detail",
    example="apps/example/tests/test_network.py::test_the_nearest_policy_on_the_chain_is_the_one_that_governs",
)
def governing_widget_policy_detail(*, tenant: Tenant, actor: Actor) -> WidgetPolicyOut:
    """The nearest policy on the hat's ancestor chain: upward resolution, never visibility."""
    # authz: `get_governing_widget_policy` asks `widget_policy.read` at the hat.
    return WidgetPolicyOut.from_orm(
        get_governing_widget_policy(tenant=tenant, org=actor.org, actor=actor)
    )


@router.get(
    "/policies/governing/",
    response=WidgetPolicyOut,
    url_name="governing_widget_policy-detail",
)
# A collection path that addresses one row without naming it: the derivation cannot see its 404.
@refuses("forbidden", "no_acting_scope", "not_found", "rate_limited")
def get_governing_widget_policy_route(request: TenantRequest) -> WidgetPolicyOut:
    """Retrieve the governing widget policy

    The governing policy; without the read, `403 forbidden`: ask an administrator.
    """
    actor, tenant = acting(request)
    return governing_widget_policy_detail(tenant=tenant, actor=actor)


@road(
    "widget_policy_archive",
    example="apps/example/tests/test_archive.py::test_a_policy_a_live_widget_names_is_blocked_and_names_the_widgets",
)
def widget_policy_archive(*, tenant: Tenant, actor: Actor, policy_id: UUID) -> WidgetPolicyOut:
    """Take one policy the hat owns out of the book."""
    # authz: `archive_widget_policy` asks `widget_policy.archive` at the policy's node.
    policy = get_widget_policy(tenant=tenant, policy_id=policy_id, org=actor.org, actor=actor)
    if not may_be_named(actor, policy):
        raise NotFound()
    return WidgetPolicyOut.from_orm(
        archive_widget_policy(tenant=tenant, actor=actor, policy=policy)
    )


@router.post(
    "/policies/{policy_id}/archive/",
    response=WidgetPolicyOut,
    url_name="widget_policy-archive",
)
@also_refuses("archive_blocked")
def archive_widget_policy_route(request: TenantRequest, policy_id: UUID) -> WidgetPolicyOut:
    """Archive a widget policy

    Archive one widget policy; `403 forbidden` unless you administer its node.
    """
    actor, tenant = acting(request)
    return widget_policy_archive(tenant=tenant, actor=actor, policy_id=policy_id)


@road(
    "widget_policy_restore",
    example="apps/example/tests/test_archive.py::test_an_archived_policy_governs_nobody_and_cannot_be_named",
)
def widget_policy_restore(*, tenant: Tenant, actor: Actor, policy_id: UUID) -> WidgetPolicyOut:
    """Put one archived policy the hat owns back in the book."""
    # authz: `restore_widget_policy` asks `widget_policy.restore` at the policy's node.
    policy = get_widget_policy(tenant=tenant, policy_id=policy_id, org=actor.org, actor=actor)
    if not may_be_named(actor, policy):
        raise NotFound()
    return WidgetPolicyOut.from_orm(
        restore_widget_policy(tenant=tenant, actor=actor, policy=policy)
    )


@router.post(
    "/policies/{policy_id}/restore/",
    response=WidgetPolicyOut,
    url_name="widget_policy-restore",
)
@also_refuses("restore_blocked")
def restore_widget_policy_route(request: TenantRequest, policy_id: UUID) -> WidgetPolicyOut:
    """Restore a widget policy

    Put one archived widget policy back; `403 forbidden` unless you administer its node.
    """
    actor, tenant = acting(request)
    return widget_policy_restore(tenant=tenant, actor=actor, policy_id=policy_id)


# golden: policy end
# golden: child entry begin
@road(
    "widget_entries_list",
    example="apps/example/tests/test_api.py::test_entries_list_query_count_does_not_grow_with_rows",
)
def widget_entries_list(
    *, tenant: Tenant, actor: Actor, widget_id: UUID | None = None
) -> QuerySet[WidgetEntry]:
    """The ledger lines the acting hat may see, newest first, optionally one widget's."""
    # authz: `list_widget_entries` asks `widget_entry.read` at the hat.
    entries: QuerySet[WidgetEntry] = list_widget_entries(
        tenant=tenant, org=actor.org, widget_id=widget_id, actor=actor
    )
    return entries


@router.get("/entries/", response=list[WidgetEntryOut], url_name="widget_entries-list")
@paginate(CursorPagination)
def list_widget_entries_route(
    request: TenantRequest, widget_id: UUID | None = None
) -> QuerySet[WidgetEntry]:
    """List ledger entries

    List ledger entries, newest first; without the read, `403 forbidden`: ask an administrator.
    """
    actor, tenant = acting(request)
    return widget_entries_list(tenant=tenant, actor=actor, widget_id=widget_id)


@road(
    "widget_entry_record",
    example="apps/example/tests/test_services.py::test_the_landing_gate_refuses_a_row_that_disagrees_with_its_widget",
)
def widget_entry_record(
    *,
    tenant: Tenant,
    actor: Actor,
    widget_id: UUID,
    kind: str = "note",
    note: str = "",
    organization_slug: str | None = None,
) -> WidgetEntryOut:
    """Append one line to a widget's ledger, at the widget's own organization."""
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    entry = record_widget_entry(
        tenant=tenant,
        actor=actor,
        widget=widget,
        kind=kind,
        note=note,
        organization_slug=organization_slug,
    )
    return WidgetEntryOut.from_orm(entry)


@router.post("/entries/", response={201: WidgetEntryOut}, url_name="widget_entry-record")
@also_refuses("archived", "merged")
def record_widget_entry_route(
    request: TenantRequest, payload: WidgetEntryIn
) -> Status[WidgetEntryOut]:
    """Record a ledger entry

    Append one entry to a widget's ledger.
    """
    actor, tenant = acting(request)
    entry = widget_entry_record(
        tenant=tenant,
        actor=actor,
        widget_id=payload.widget_id,
        kind=payload.kind,
        note=payload.note,
        organization_slug=payload.organization_slug,
    )
    return Status(201, entry)


# golden: child entry end
# golden: bulk history duplicate attach merge import begin
@road(
    "bulk_widgets",
    example="apps/example/tests/test_doors_over_the_wire.py::test_a_partial_bulk_answers_the_same_three_outcomes_on_the_machine_door",
)
def bulk_widgets(
    *,
    tenant: Tenant,
    actor: Actor,
    verb: str,
    ids: list[UUID],
    organization_id: UUID | None = None,
    owner_id: UUID | None = None,
) -> WidgetBulkOut:
    """One verb over a selection, each id through the widget's service (`run_bulk`)."""
    if verb != "move" and (organization_id is not None or owner_id is not None):
        raise Invalid({"organization_id": ["Only a move names where the widgets go."]})

    def resolve(pk: UUID) -> Widget:
        return cast(Widget, resolve_subject(actor, "widget", pk))

    act: Callable[[Widget], Widget]
    settled: Callable[..., bool]
    if verb == "move":
        # A destination outside the hat's subtree refuses the whole batch before any item runs.
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

    Run one verb — `archive`, `restore` or `move` — over up to 200 widgets.
    """
    actor, tenant = acting(request)
    return bulk_widgets(
        tenant=tenant,
        actor=actor,
        verb=payload.verb,
        ids=payload.ids,
        organization_id=getattr(payload, "organization_id", None),
        owner_id=getattr(payload, "owner_id", None),
    )


# golden: archive version move begin
# golden: noun begin
@road(
    "widget_detail",
    example="apps/example/tests/test_doors_over_the_wire.py::test_the_two_doors_put_the_same_key_set_on_the_wire",
)
def widget_detail(*, tenant: Tenant, actor: Actor, widget_id: UUID) -> WidgetDetailOut:
    """One widget this hat reaches, archived or not, with what this viewer may press."""
    # authz: `get_widget` asks `widget.read` at the row.
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    # golden: noun end
    # golden: archive version move bulk history duplicate end
    widget.tags = list_widget_tags(tenant=tenant, actor=actor, widget=widget)  # type: ignore[attr-defined]
    # golden: archive version move bulk history duplicate begin
    # golden: noun begin
    return WidgetDetailOut.from_orm(with_allowed_acts([widget], actor)[0])


@router.get("/{widget_id}/", response=WidgetDetailOut, url_name="widget-detail")
def retrieve_widget(request: TenantRequest, widget_id: UUID) -> WidgetDetailOut:
    """Retrieve a widget

    One widget and its `tags`; without the read, `403 forbidden`: ask an administrator.
    """
    actor, tenant = acting(request)
    return widget_detail(tenant=tenant, actor=actor, widget_id=widget_id)


@road(
    "widget_archive",
    example="apps/example/tests/test_doors_over_the_wire.py::test_one_press_is_one_body_on_rest_mcp_and_the_outbox",
)
def widget_archive(*, tenant: Tenant, actor: Actor, widget_id: UUID) -> WidgetOut:
    """Take one widget this hat reaches out of the book."""
    # authz: `archive_widget` asks `widget.archive` at the row's node.
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    archived = archive_widget(tenant=tenant, actor=actor, widget=widget)
    return WidgetOut.from_orm(with_allowed_acts([archived], actor)[0])


@router.post("/{widget_id}/archive/", response=WidgetOut, url_name="widget-archive")
@also_refuses("archive_blocked")
def archive_widget_route(request: TenantRequest, widget_id: UUID) -> WidgetOut:
    """Archive a widget

    Archive one widget; `403 forbidden` unless you administer its organization.
    """
    actor, tenant = acting(request)
    return widget_archive(tenant=tenant, actor=actor, widget_id=widget_id)


@road(
    "widget_restore",
    example="apps/example/tests/test_doors_over_the_wire.py::test_one_press_is_one_body_on_rest_mcp_and_the_outbox",
)
def widget_restore(*, tenant: Tenant, actor: Actor, widget_id: UUID) -> WidgetOut:
    """Put one archived widget this hat reaches back in the book."""
    # authz: `restore_widget` asks `widget.restore` at the row's node.
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    restored = restore_widget(tenant=tenant, actor=actor, widget=widget)
    return WidgetOut.from_orm(with_allowed_acts([restored], actor)[0])


@router.post("/{widget_id}/restore/", response=WidgetOut, url_name="widget-restore")
@also_refuses("restore_blocked")
# golden: noun end
# golden: archive version move bulk history duplicate attach end
@also_refuses("merged")
# golden: archive version move bulk history duplicate attach begin
# golden: noun begin
def restore_widget_route(request: TenantRequest, widget_id: UUID) -> WidgetOut:
    """Restore a widget

    Put one archived widget back; `403 forbidden` unless you administer its organization.
    """
    actor, tenant = acting(request)
    return widget_restore(tenant=tenant, actor=actor, widget_id=widget_id)


# golden: archive end
@road(
    "widget_update",
    example="apps/example/tests/test_doors_over_the_wire.py::test_each_family_verb_is_one_body_on_rest_mcp_and_the_outbox",
)
def widget_update(
    *,
    tenant: Tenant,
    actor: Actor,
    widget_id: UUID,
    version: int,
    name: str | None = None,
    notes: str | None = None,
    # golden: noun end
    # golden: version move bulk history duplicate attach merge import end
    # golden: policy begin
    policy_id: UUID | None = None,
    # golden: policy end
    # golden: noun begin
    # golden: field due_at begin
    due_at: datetime | None = None,
    clear_due_at: bool = False,
    # golden: field due_at end
    # golden: version move bulk history duplicate attach merge import begin
) -> WidgetOut:
    """Change what was sent of one widget, at the version the caller read."""
    # authz: `update_widget` asks `widget.update` at the row's node.
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    # Only what was sent reaches the service, so the history names what this edit changed.
    changes: dict[str, Any] = {
        field: value for field, value in {"name": name, "notes": notes}.items() if value is not None
    }
    # golden: noun end
    # golden: version move bulk history duplicate attach merge import end
    # golden: policy begin
    policy = resolve_named_policy(tenant=tenant, actor=actor, policy_id=policy_id)
    if policy is not None and not may_be_named(actor, policy):
        raise NotFound()
    # golden: policy end
    # golden: policy begin
    if policy is not None:
        changes["policy"] = policy
    # golden: policy end
    # golden: noun begin
    # golden: field due_at begin
    if due_at is not None:
        changes["due_at"] = due_at
    if clear_due_at:
        changes["clear_due_at"] = True
    # golden: field due_at end
    # golden: version move bulk history duplicate attach merge import begin
    updated = update_widget(tenant=tenant, actor=actor, widget=widget, version=version, **changes)
    return WidgetOut.from_orm(with_allowed_acts([updated], actor)[0])


@router.patch("/{widget_id}/", response=WidgetOut, url_name="widget-update")
@also_refuses("archived", "stale_version")
# golden: noun end
# golden: version move bulk history duplicate attach end
@also_refuses("merged")
# golden: version move bulk history duplicate attach begin
# golden: noun begin
def update_widget_route(request: TenantRequest, widget_id: UUID, payload: WidgetPatch) -> WidgetOut:
    """Update a widget

    Change a widget; `403 forbidden` unless it is yours or you administer its node.
    """
    actor, tenant = acting(request)
    return widget_update(
        tenant=tenant,
        actor=actor,
        widget_id=widget_id,
        version=payload.version,
        name=payload.name,
        notes=payload.notes,
        # golden: noun end
        # golden: version move bulk history duplicate attach merge import end
        # golden: policy begin
        policy_id=payload.policy_id,
        # golden: policy end
        # golden: noun begin
        # golden: field due_at begin
        due_at=payload.due_at,
        clear_due_at=bool(payload.clear_due_at),
        # golden: field due_at end
        # golden: version move bulk history duplicate attach merge import begin
    )
    # golden: noun end


# golden: version end
@road(
    "widget_move",
    example="apps/example/tests/test_doors_over_the_wire.py::test_each_family_verb_is_one_body_on_rest_mcp_and_the_outbox",
)
def widget_move(
    *,
    tenant: Tenant,
    actor: Actor,
    widget_id: UUID,
    version: int,
    organization_id: UUID | None = None,
    owner_id: UUID | None = None,
) -> WidgetOut:
    """Re-home one widget inside the hat's subtree; hand it over if an owner is named."""
    # authz: `move_widget` asks `widget.move` at both ends.
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    moved = move_widget(
        tenant=tenant,
        actor=actor,
        widget=widget,
        organization=move_destination(
            tenant=tenant, actor=actor, widget=widget, to=organization_id
        ),
        owner_id=owner_id,
        version=version,
    )
    return WidgetOut.from_orm(with_allowed_acts([moved], actor)[0])


@router.post("/{widget_id}/move/", response=WidgetOut, url_name="widget-move")
@also_refuses("archived", "move_blocked", "stale_version")
# golden: move bulk history duplicate attach end
@also_refuses("merged")
# golden: move bulk history duplicate attach begin
def move_widget_route(
    request: TenantRequest, widget_id: UUID, payload: VersionedMoveIn
) -> WidgetOut:
    """Move a widget

    Re-home a widget (and maybe its owner); `403 forbidden` unless you administer both.
    """
    actor, tenant = acting(request)
    return widget_move(
        tenant=tenant,
        actor=actor,
        widget_id=widget_id,
        version=payload.version,
        organization_id=payload.organization_id,
        owner_id=payload.owner_id,
    )


def move_destination(
    *, tenant: Tenant, actor: Actor, widget: Widget, to: UUID | None
) -> Organization:
    """Where a move is going: the named node inside the hat's subtree, or where it is."""
    if to is None:
        return widget.organization
    return get_organization(tenant=tenant, org=actor.org, organization_id=to, actor=actor)


# golden: version begin
# golden: noun begin
@road(
    "widget_history_list",
    example="apps/example/tests/test_doors_over_the_wire.py::test_each_family_verb_is_one_body_on_rest_mcp_and_the_outbox",
)
def widget_history_list(*, tenant: Tenant, actor: Actor, widget_id: UUID) -> QuerySet[AuditEntry]:
    """What was done to one widget this hat reaches, newest first."""
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    return list_history(tenant=tenant, actor=actor, row=widget)


@router.get("/{widget_id}/history/", response=list[HistoryEntryOut], url_name="widget_history-list")
@paginate(CursorPagination)
def list_widget_history_route(request: TenantRequest, widget_id: UUID) -> QuerySet[AuditEntry]:
    """List a widget's history

    What happened to one widget, newest first.
    """
    actor, tenant = acting(request)
    return widget_history_list(tenant=tenant, actor=actor, widget_id=widget_id)


# golden: noun end


# golden: version move bulk history end
@road(
    "widget_duplicate",
    example="apps/example/tests/test_doors_over_the_wire.py::test_duplicate_and_merge_are_one_row_on_four_doors_for_two_viewers",
)
def widget_duplicate(
    *, tenant: Tenant, actor: Actor, widget_id: UUID, idempotency_key: str = ""
) -> WidgetOut:
    """A copy of one widget this hat reaches, made at the hat and owned by the presser."""
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    copy = duplicate_widget(
        tenant=tenant, actor=actor, widget=widget, idempotency_key=idempotency_key
    )
    return WidgetOut.from_orm(with_allowed_acts([copy], actor)[0])


@router.post("/{widget_id}/duplicate/", response={201: WidgetOut}, url_name="widget-duplicate")
@also_refuses("archived", "merged", "invalid")
def duplicate_widget_route(request: TenantRequest, widget_id: UUID) -> Status[WidgetOut]:
    """Duplicate a widget

    Make a new widget from this one. Takes no body.
    """
    actor, tenant = acting(request)
    copy = widget_duplicate(
        tenant=tenant,
        actor=actor,
        widget_id=widget_id,
        idempotency_key=request.headers.get(IDEMPOTENCY_KEY_HEADER, ""),
    )
    return Status(201, copy)


# golden: duplicate attach end
@road(
    "widget_merge_detail",
    example="apps/example/tests/test_duplicate_merge.py::test_the_dry_run_names_what_would_leave_the_loser_and_writes_nothing",
)
def widget_merge_detail(
    *, tenant: Tenant, actor: Actor, widget_id: UUID, into: UUID
) -> WidgetMergePreviewOut:
    """What merging one widget into another would move. Writes nothing."""
    # authz: `get_widget_merge_preview` asks `widget.merge` of both records.
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


@router.get("/{widget_id}/merge/", response=WidgetMergePreviewOut, url_name="widget_merge-detail")
@also_refuses("invalid")
def preview_widget_merge_route(
    request: TenantRequest, widget_id: UUID, into: UUID
) -> WidgetMergePreviewOut:
    """Preview a widget merge

    What a merge into `?into=` WOULD move; `403 forbidden` unless you administer both.
    """
    actor, tenant = acting(request)
    return widget_merge_detail(tenant=tenant, actor=actor, widget_id=widget_id, into=into)


@road(
    "widget_merge",
    example="apps/example/tests/test_doors_over_the_wire.py::test_duplicate_and_merge_are_one_row_on_four_doors_for_two_viewers",
)
def widget_merge(
    *, tenant: Tenant, actor: Actor, widget_id: UUID, into_id: UUID, version: int, into_version: int
) -> WidgetOut:
    """Fold one widget into another at the versions read; answers the survivor."""
    # authz: `merge_widget` asks `widget.merge` of both records.
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    survivor = get_widget(tenant=tenant, widget_id=into_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget) or not may_be_named(actor, survivor):
        raise NotFound()
    merged = merge_widget(
        tenant=tenant,
        actor=actor,
        widget=widget,
        into=survivor,
        version=version,
        into_version=into_version,
    )
    return WidgetOut.from_orm(with_allowed_acts([merged], actor)[0])


@router.post("/{widget_id}/merge/", response=WidgetOut, url_name="widget-merge")
@also_refuses("merge_blocked", "merged", "archived", "stale_version")
def merge_widget_route(
    request: TenantRequest, widget_id: UUID, payload: WidgetMergeIn
) -> WidgetOut:
    """Merge a widget into another

    Fold this into `into_id`, with no undo; `403 forbidden` unless you administer both.
    """
    actor, tenant = acting(request)
    return widget_merge(
        tenant=tenant,
        actor=actor,
        widget_id=widget_id,
        into_id=payload.into_id,
        version=payload.version,
        into_version=payload.into_version,
    )


# golden: merge import end
# golden: workflow onboard begin
@road(
    "widget_approve",
    example="apps/example/tests/test_mcp.py::test_both_doors_leave_audit_rows_that_differ_only_in_the_door",
)
def widget_approve(*, tenant: Tenant, actor: Actor, widget_id: UUID) -> WidgetOut:
    """Approve the onboarding under way for one widget this hat reaches."""
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    approved = approve_widget(tenant=tenant, actor=actor, widget=widget)
    return WidgetOut.from_orm(with_allowed_acts([approved], actor)[0])


@router.post("/{widget_id}/approve/", response=WidgetOut, url_name="widget-approve")
# golden: workflow onboard end
@also_refuses("archived", "merged")
# golden: workflow onboard begin
@also_refuses("archived")
def approve_widget_route(request: TenantRequest, widget_id: UUID) -> WidgetOut:
    """Approve a widget

    Approve a widget that is waiting to be onboarded.
    """
    actor, tenant = acting(request)
    return widget_approve(tenant=tenant, actor=actor, widget_id=widget_id)


# golden: workflow onboard end


# golden: noun begin
@road(
    "widget_delete",
    example="apps/example/tests/test_mcp.py::test_delete_widget_removes_the_row_and_says_which",
)
def widget_delete(*, tenant: Tenant, actor: Actor, widget_id: UUID) -> WidgetOut:
    """Delete one widget this hat reaches; answers the row that went, with no acts."""
    # authz: `delete_widget` asks `widget.delete` at the row's node.
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
    if not may_be_named(actor, widget):
        raise NotFound()
    return WidgetOut.from_orm(delete_widget(tenant=tenant, actor=actor, widget=widget))


@router.delete("/{widget_id}/", response={204: None}, url_name="widget-delete")
@also_refuses("archived", "merged", "merge_survivor")
def delete_widget_route(request: TenantRequest, widget_id: UUID) -> Status[None]:
    """Delete a widget

    Delete a widget; `403 forbidden` unless it is yours or you administer its node.
    """
    actor, tenant = acting(request)
    widget_delete(tenant=tenant, actor=actor, widget_id=widget_id)
    return Status(204, None)


# golden: noun end
