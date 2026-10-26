"""Where this app's workflows touch the world (rules 9, 10); plain `def`, connections closed."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from importlib import import_module
from typing import Any

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import close_old_connections
from django.utils import timezone
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from apps.core import mail
from apps.core.asyncdb import run_async
from apps.core.context import current_actor
from apps.core.exceptions import NotFound
from apps.core.log import get_logger
from apps.core.models import Organization, Tenant
from apps.core.schedules import ScheduleDeclaration, daily_purge, platform_schedule
from apps.core.services import apply_organization_move
from apps.workflows import services
from apps.workflows.context import platform_context, workflow_context
from apps.workflows.models import WorkflowRun
from apps.workflows.services import finish_run
from apps.workflows.types import (
    MarkRunFinished,
    MoveOrganization,
    PurgeFinishedRuns,
    ReconcileRuns,
    SendEmail,
)

log = get_logger(__name__)

#: How old a `RUNNING` row with no `run_id` is before the sweep believes nobody will start it.
RECONCILE_AFTER = timedelta(minutes=15)
RECONCILE_EVERY = timedelta(minutes=5)

#: The names the three periodic workflows are discovered under, spelled once.
RECONCILE_WORKFLOW = "ReconcileRunsWorkflow"
PURGE_RUNS_WORKFLOW = "PurgeFinishedRunsWorkflow"
PURGE_SESSIONS_WORKFLOW = "PurgeExpiredSessionsWorkflow"


@activity.defn(name="mark_run_finished", no_thread_cancel_exception=True)
def mark_run_finished(payload: MarkRunFinished) -> str:
    """Close a run's visibility row and report the tenant slug it acted for; idempotent.

    The one activity here reading `platform_context()`: it closes platform runs (ADR workflows-3).
    """
    close_old_connections()
    try:
        tenant, _user_id, _org = platform_context()
        finish_run(
            tenant=tenant,
            workflow_id=payload.workflow_id,
            status=payload.status,
            error=payload.error,
        )
        return tenant.slug if tenant is not None else ""
    finally:
        close_old_connections()


@activity.defn(name="send_email", no_thread_cancel_exception=True)
def send_email(payload: SendEmail) -> int:
    """Render one email and hand it to the backend; a retry may deliver a second copy.

    why-not exactly-once: an email cannot be unsent; the service's deterministic id starts one run.
    """
    close_old_connections()
    try:
        tenant, _user_id, _org = workflow_context()
        return mail.send_now(
            to=payload.to,
            subject=payload.subject,
            template=payload.template,
            context=payload.context,
            tenant=tenant,
        )
    finally:
        close_old_connections()


@activity.defn(name="rewrite_organization_paths", no_thread_cancel_exception=True)
def rewrite_organization_paths(payload: MoveOrganization) -> str:
    """Re-parent a node and rewrite its subtree's paths, as the system under the run's hat."""
    close_old_connections()
    try:
        actor = current_actor()
        tenant = actor.tenant
        scoped = Organization.objects.for_tenant(tenant)
        organization = scoped.filter(pk=payload.organization_id).first()
        new_parent = scoped.filter(pk=payload.new_parent_id).first()
        if tenant is None or organization is None or new_parent is None:
            raise NotFound("That organization, or the parent it was moving to, is gone.")
        moved = apply_organization_move(
            tenant=tenant,
            organization=organization,
            new_parent=new_parent,
            actor=actor,
        )
        return str(moved.path)
    finally:
        close_old_connections()


# --- The reconciler: rows promised an execution that never got one ----------


def reconcile_after_seconds() -> int:
    """`RECONCILE_AFTER` as the integer that crosses a Temporal history."""
    return int(RECONCILE_AFTER.total_seconds())


def stranded_runs(*, older_than: datetime) -> list[WorkflowRun]:
    """Every population's rows that claim to be running and name no execution (`run_id=""`).

    Read per population (rule 8): one `for_tenant` per tenant, then `for_platform()`.
    """
    found: list[WorkflowRun] = []
    for tenant in Tenant.objects.all().iterator():
        found.extend(
            WorkflowRun.objects.for_tenant(tenant).filter(
                status=WorkflowRun.Status.RUNNING,
                run_id="",
                started_at__lt=older_than,
            )
        )
    found.extend(
        # rule-8: the platform population is the declared null-tenant one (ADR
        # workflows-3); for_tenant stays fail-closed and can never reach it.
        WorkflowRun.objects.for_platform().filter(
            status=WorkflowRun.Status.RUNNING,
            run_id="",
            started_at__lt=older_than,
        )
    )
    return found


#: What Temporal says about an execution, reduced to what this sweep decides on:
#: `None` means the server has no such execution, a status means it has one.
_Outcome = WorkflowExecutionStatus | None


async def describe_execution(client: Client, workflow_id: str) -> _Outcome:
    """What became of this id: `None` only for `NOT_FOUND`; any other error raises."""
    try:
        description = await client.get_workflow_handle(workflow_id).describe()
    except RPCError as error:
        if error.status is RPCStatusCode.NOT_FOUND:
            return None
        raise
    return description.status


#: How a closed execution's status becomes the row's word; anything unnamed is `failed`, named in
#: `error`. `CANCELED` is Temporal's spelling and `cancelled` the row's (ADR workflows-7).
CLOSED_AS: dict[WorkflowExecutionStatus, str] = {
    WorkflowExecutionStatus.COMPLETED: WorkflowRun.Status.COMPLETED,
    WorkflowExecutionStatus.CANCELED: WorkflowRun.Status.CANCELLED,
}

NEVER_STARTED = (
    "This run was recorded and never started: no execution exists under its id, and the row "
    "is older than the reconciler's threshold. The process died between the commit that wrote "
    "the row and the client call that would have started the work."
)


@activity.defn(name="reconcile_runs", no_thread_cancel_exception=True)
def reconcile_runs(window: ReconcileRuns) -> int:
    """Close the rows whose execution was promised and never started; returns how many it closed.

    No execution: `failed`, never-started. A closed one: its outcome through `CLOSED_AS`. A running
    one: left alone. A describe that errored: skipped — an unanswered question is not a `no`.
    """
    close_old_connections()
    try:
        cutoff = timezone.now() - timedelta(seconds=window.after_seconds)
        stranded = stranded_runs(older_than=cutoff)
        if not stranded:
            return 0

        async def ask() -> dict[str, _Outcome]:
            from apps.workflows.client import get_client

            client = await get_client()
            answers: dict[str, _Outcome] = {}
            for row in stranded:
                try:
                    answers[row.workflow_id] = await describe_execution(client, row.workflow_id)
                except RPCError as error:
                    log.warning(
                        "workflows.reconcile.skipped",
                        workflow_id=row.workflow_id,
                        status=str(error.status),
                    )
            return answers

        answers = run_async(ask)
        closed = 0
        for row in stranded:
            if row.workflow_id not in answers:
                continue
            outcome = answers[row.workflow_id]
            if outcome is WorkflowExecutionStatus.RUNNING:
                continue
            if outcome is None:
                finish_run(
                    tenant=row.tenant,
                    workflow_id=row.workflow_id,
                    status=WorkflowRun.Status.FAILED,
                    error=NEVER_STARTED,
                )
            else:
                status = CLOSED_AS.get(outcome, WorkflowRun.Status.FAILED)
                finish_run(
                    tenant=row.tenant,
                    workflow_id=row.workflow_id,
                    status=status,
                    # A run that ended the way it was asked to — completed, or
                    # stopped on purpose — has nothing to explain. Only the
                    # residue does.
                    error=(
                        ""
                        if status != WorkflowRun.Status.FAILED
                        else f"The execution closed as {outcome.name}."
                    ),
                )
            closed += 1
        log.info("workflows.reconcile.swept", status=str(closed))
        return closed
    finally:
        close_old_connections()


@activity.defn(name="purge_finished_runs", no_thread_cancel_exception=True)
def purge_finished_runs(window: PurgeFinishedRuns) -> int:
    """Apply the run ledger's retention window through the service; the clock is read here."""
    close_old_connections()
    try:
        before = timezone.now() - timedelta(seconds=window.retention_seconds)
        removed = services.purge_finished_runs(before=before, tenant=None).count
        log.info("workflows.purge.runs", status=str(removed))
        return removed
    finally:
        close_old_connections()


@activity.defn(name="purge_expired_sessions", no_thread_cancel_exception=True)
def purge_expired_sessions() -> int:
    """Clear expired sessions through the configured engine; returns how many were eligible.

    why-not a `@service`: the rows are `django.contrib.sessions`', and its engine is their one door.
    The count is read before the clear, so a session expiring between the two is an undercount.
    """
    close_old_connections()
    try:
        eligible = Session.objects.filter(expire_date__lt=timezone.now()).count()
        import_module(settings.SESSION_ENGINE).SessionStore.clear_expired()
        log.info("workflows.purge.sessions", status=str(eligible))
        return eligible
    finally:
        close_old_connections()


# --- The schedules -----------------------------------------------------------


def finished_run_retention_seconds() -> int:
    """`services.FINISHED_RUN_RETENTION` as the integer the purge's action carries."""
    return int(services.FINISHED_RUN_RETENTION.total_seconds())


#: `platform:workflows:reconcile:<queue>`, every `RECONCILE_EVERY` (ADR workflows-5).
RECONCILE_RUNS = platform_schedule(
    app="workflows",
    noun="reconcile",
    workflow=RECONCILE_WORKFLOW,
    every=RECONCILE_EVERY,
    arg=ReconcileRuns(after_seconds=reconcile_after_seconds()),
    name="workflows.reconcile-runs",
    log_prefix="workflows",
)

#: `platform:workflows:purge-runs:<queue>` — the far end of `WorkflowRun.lifecycle` (rule 31).
PURGE_FINISHED_RUNS = daily_purge(
    app="workflows",
    noun="purge-runs",
    workflow=PURGE_RUNS_WORKFLOW,
    arg=PurgeFinishedRuns(retention_seconds=finished_run_retention_seconds()),
    name="workflows.purge-finished-runs",
    log_prefix="workflows",
)

#: `platform:workflows:purge-sessions:<queue>` — the far end of `lifecycle.py`'s `django_session`.
PURGE_EXPIRED_SESSIONS = daily_purge(
    app="workflows",
    noun="purge-sessions",
    workflow=PURGE_SESSIONS_WORKFLOW,
    arg=None,
    name="workflows.purge-expired-sessions",
    log_prefix="workflows",
)


ACTIVITIES: list[Callable[..., Any]] = [
    mark_run_finished,
    send_email,
    rewrite_organization_paths,
    reconcile_runs,
    purge_finished_runs,
    purge_expired_sessions,
]

SCHEDULES: list[ScheduleDeclaration] = [
    RECONCILE_RUNS,
    PURGE_FINISHED_RUNS,
    PURGE_EXPIRED_SESSIONS,
]
