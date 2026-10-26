"""`Import` declares `purged` and the sweep really purges it, audited; `ImportRow` dies with it.

Rule 31 walks the declaration's chain; this module drives what a static walk cannot see.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from temporalio.client import ScheduleActionStartWorkflow

from apps.core.audit import AuditEntry
from apps.core.exceptions import Invalid
from apps.core.lifecycle import LifecycleKind, lifecycle_of
from apps.core.models import Organization, Tenant
from apps.core.time import now
from apps.djb_imports import activities, services
from apps.djb_imports.models import IMPORT_RETENTION_DAYS, Import, ImportRow
from apps.djb_imports.types import PURGE_WORKFLOW, PurgeImports
from apps.workflows.services import check_workflow_id

pytestmark = pytest.mark.django_db

PURGED_BY = "apps.djb_imports.services.purge_imports"
TASK_QUEUE = "djb-imports-tests"
WELL_PAST = -(IMPORT_RETENTION_DAYS + 10)
WELL_INSIDE = -(IMPORT_RETENTION_DAYS - 10)


def test_import_is_purged_by_the_service_and_its_rows_are_bounded_by_it() -> None:
    """IM.5: the two declarations, and the CASCADE that makes `bounded` true."""
    declared = lifecycle_of(Import)
    assert declared is not None
    assert declared.kind == LifecycleKind.PURGED
    assert declared.purged_by == PURGED_BY
    rows = lifecycle_of(ImportRow)
    assert rows is not None
    assert rows.kind == LifecycleKind.BOUNDED
    from django.db import models

    parent = ImportRow._meta.get_field("run")
    assert parent.remote_field.on_delete is models.CASCADE


def test_the_sweep_is_one_platform_id_the_run_fence_accepts() -> None:
    """The schedule and its run are `platform:djb_imports:purge:<queue>`; the window rides along."""
    expected = f"platform:djb_imports:purge:{TASK_QUEUE}"
    assert activities.PURGE_IMPORTS in activities.SCHEDULES
    assert activities.PURGE_IMPORTS.schedule_id(TASK_QUEUE) == expected
    action = activities.PURGE_IMPORTS.schedule(TASK_QUEUE).action
    assert isinstance(action, ScheduleActionStartWorkflow)
    assert action.workflow == PURGE_WORKFLOW
    assert action.args == [PurgeImports(retention_days=IMPORT_RETENTION_DAYS)]
    assert action.id == expected
    assert check_workflow_id(id=action.id, tenant=None) == expected


def _run(tenant: Tenant, org: Organization, status: str, age_days: int, name: str) -> Import:
    run = Import.objects.create(
        tenant=tenant,
        organization=org,
        kind="widget",
        status=status,
        file_name=f"{name}.csv",
        digest=name.ljust(64, "0"),
    )
    ImportRow.objects.create(
        tenant=tenant,
        organization=org,
        run=run,
        row_no=1,
        data={"name": name},
        outcome_preview="create",
    )
    Import.objects.filter(pk=run.pk).update(updated_at=now() + timedelta(days=age_days))
    return run


def test_the_sweep_takes_settled_runs_past_the_window_and_leaves_the_rest(
    tenant: Tenant, root_org: Organization
) -> None:
    """Both directions: what went (with its rows), and what is still there."""
    gone = [
        _run(tenant, root_org, Import.Status.IMPORTED, WELL_PAST, "imported"),
        _run(tenant, root_org, Import.Status.FAILED, WELL_PAST, "failed"),
        _run(tenant, root_org, Import.Status.PREVIEWED, WELL_PAST, "abandoned"),
    ]
    kept = [
        _run(tenant, root_org, Import.Status.IMPORTED, WELL_INSIDE, "recent"),
        _run(tenant, root_org, Import.Status.CHECKING, WELL_PAST, "checking"),
        _run(tenant, root_org, Import.Status.IMPORTING, WELL_PAST, "importing"),
    ]

    outcome = services.purge_imports(
        before=now() - timedelta(days=IMPORT_RETENTION_DAYS), tenant=None
    )

    assert outcome.count == 3
    audited = AuditEntry.objects.filter(tenant=None, action__endswith="purge_imports").get()
    assert (audited.object_type, audited.object_id) == ("djb_imports.Import", None)
    assert (audited.actor_kind, audited.actor_user_id) == ("system", None)
    assert not Import.objects.filter(pk__in=[run.pk for run in gone]).exists()
    assert not ImportRow.objects.filter(run_id__in=[run.pk for run in gone]).exists()
    assert set(Import.objects.values_list("pk", flat=True)) == {run.pk for run in kept}
    assert ImportRow.objects.count() == 3


def test_the_sweep_refuses_to_be_narrowed_to_one_tenant(tenant: Tenant) -> None:
    with pytest.raises(Invalid):
        services.purge_imports(before=now(), tenant=tenant)  # type: ignore[arg-type]  # the refusal under test
