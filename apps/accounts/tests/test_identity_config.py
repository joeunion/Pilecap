"""Identity configuration as code: the row is the intent (ADR ident-2).

What is proved here is the seam, not the client: a service records what we want
and hands the materialisation to a durable run, **on commit** — so a Zitadel
that is down is a run that finishes later rather than a legitimate row that
never landed. The management API itself is nowhere near these tests, which is
the posture ident-5 asks for and the reason the whole suite passes with Zitadel
stopped.

`transaction=True` where an `on_commit` hook has to fire, with the
`recorded_workflow_starts` fixture from `apps/conftest.py`: the `WorkflowRun` row
is still written in the caller's transaction and the hook still runs — what is
skipped is the dial, because the subject of these tests is the *decision to
start*, not the run.
"""

from __future__ import annotations

import pytest

from apps.accounts.models import SsoConnection
from apps.accounts.services import (
    SYNC_IDENTITY_CONFIG_WORKFLOW,
    _identity_config_key,
    sync_identity_config,
    update_sso_connection,
)
from apps.accounts.types import KIND_SSO_CONNECTION, IdentityConfigApplied
from apps.core.actor import Actor
from apps.core.exceptions import Conflict, Forbidden
from apps.core.models import Tenant
from apps.workflows.models import WorkflowRun
from apps.workflows.services import workflow_id


def expected_id(tenant: Tenant, connection: SsoConnection) -> str:
    """The id the service will have used — derived here, never remembered."""
    return workflow_id(
        tenant=tenant,
        app="accounts",
        noun="identity_config",
        key=_identity_config_key(connection),
    )


@pytest.mark.django_db(transaction=True)
def test_syncing_records_the_intent_and_starts_a_run_on_commit(
    recorded_workflow_starts: None,
    tenant: Tenant,
    owner_actor: Actor,
    sso_connection: SsoConnection,
) -> None:
    """W2R2-2's first half: the row says pending, and a run exists for it.

    The fixture's `create_sso_connection` has already asked once (W2-R5), so the
    row arrives at `pending` rather than `unmanaged` — asking again under the
    same unchanged intent is the *same* run, which is the property house rule 18
    exists for and the reason this still reads as one assertion.
    """
    assert sso_connection.sync_state == SsoConnection.SyncState.PENDING

    sync_identity_config(tenant=tenant, actor=owner_actor, connection=sso_connection)

    sso_connection.refresh_from_db()
    assert sso_connection.sync_state == SsoConnection.SyncState.PENDING
    # Nothing has been materialised yet, and the row says so rather than
    # carrying a resource id nobody got back.
    assert sso_connection.zitadel_idp_id == ""

    run = WorkflowRun.objects.for_tenant(tenant).get(
        workflow_id=expected_id(tenant, sso_connection)
    )
    assert run.type == SYNC_IDENTITY_CONFIG_WORKFLOW
    assert run.status == WorkflowRun.Status.RUNNING


@pytest.mark.django_db(transaction=True)
def test_a_rolled_back_sync_leaves_no_run(
    recorded_workflow_starts: None,
    tenant: Tenant,
    owner_actor: Actor,
    sso_connection: SsoConnection,
) -> None:
    """C2's classic, and the reason the start is deferred to `on_commit`.

    A service that called the management API inline would have configured a
    live identity provider for a transaction that then rolled back. Here the
    visibility row goes with the transaction and the durable run is never
    started, so the world outside the database learns nothing about a write
    that did not happen.

    Measured as a delta since W2-R5: the fixture's own `create_sso_connection`
    committed one run before this test began, so what has to be true is that the
    *rolled-back* sync added nothing and moved nothing — which is the same
    property, counted the honest way now that creating a connection is itself a
    materialisation.
    """
    from django.db import transaction

    before_state = sso_connection.sync_state
    before_runs = set(
        WorkflowRun.objects.for_tenant(tenant)
        .filter(type=SYNC_IDENTITY_CONFIG_WORKFLOW)
        .values_list("workflow_id", flat=True)
    )

    with pytest.raises(RuntimeError), transaction.atomic():
        update_sso_connection(
            tenant=tenant,
            actor=owner_actor,
            connection=sso_connection,
            issuer="https://idp-rolled-back.acme.example",
        )
        raise RuntimeError("the caller changed its mind")

    sso_connection.refresh_from_db()
    assert sso_connection.sync_state == before_state
    assert sso_connection.issuer != "https://idp-rolled-back.acme.example"
    assert (
        set(
            WorkflowRun.objects.for_tenant(tenant)
            .filter(type=SYNC_IDENTITY_CONFIG_WORKFLOW)
            .values_list("workflow_id", flat=True)
        )
        == before_runs
    )


@pytest.mark.django_db(transaction=True)
def test_the_same_configuration_twice_is_one_run(
    recorded_workflow_starts: None,
    tenant: Tenant,
    owner_actor: Actor,
    sso_connection: SsoConnection,
) -> None:
    """Rule 18's property: a retried service asks for the same run, not a second.

    The id is derived from the connection and a digest of what is being
    materialised, so a double-click, a resent request or a retried caller all
    arrive at the row that is already there.
    """
    sync_identity_config(tenant=tenant, actor=owner_actor, connection=sso_connection)
    sync_identity_config(tenant=tenant, actor=owner_actor, connection=sso_connection)

    # Three asks now — the fixture's create, and these two — and one run, which
    # is exactly what the deterministic id is for.
    runs = WorkflowRun.objects.for_tenant(tenant).filter(type=SYNC_IDENTITY_CONFIG_WORKFLOW)
    assert runs.count() == 1


@pytest.mark.django_db(transaction=True)
def test_changed_configuration_is_a_new_run(
    recorded_workflow_starts: None,
    tenant: Tenant,
    owner_actor: Actor,
    sso_connection: SsoConnection,
) -> None:
    """And the other half: a connection that now points somewhere else is new work.

    The key is a digest of the intent, so this is what keeps "the same twice is
    one run" from also meaning "a connection can only ever be synced once".
    """
    sync_identity_config(tenant=tenant, actor=owner_actor, connection=sso_connection)
    first = expected_id(tenant, sso_connection)

    update_sso_connection(
        tenant=tenant,
        actor=owner_actor,
        connection=sso_connection,
        issuer="https://idp-2.acme.example",
    )
    sync_identity_config(tenant=tenant, actor=owner_actor, connection=sso_connection)
    second = expected_id(tenant, sso_connection)

    assert first != second
    assert WorkflowRun.objects.for_tenant(tenant).filter(workflow_id=first).exists()
    assert WorkflowRun.objects.for_tenant(tenant).filter(workflow_id=second).exists()


@pytest.mark.django_db(transaction=True)
def test_resyncing_unchanged_applied_configuration_is_refused(
    recorded_workflow_starts: None,
    tenant: Tenant,
    owner_actor: Actor,
    sso_connection: SsoConnection,
) -> None:
    """The declared consequence of the deterministic id, pinned rather than left.

    `record_run` refuses a finished id — "re-running completed work is a
    decision about a new key" — so asking to re-sync configuration that has not
    changed and has already been applied is a `Conflict`. That is the shape ADR
    ident-2 chose when it deliberately did not build the auto-repairing
    reconciler; `manage.py zitadel_audit` is what makes console drift visible in
    the meantime. If this test starts failing, somebody has built the
    reconciler and this is where to say so.
    """
    sync_identity_config(tenant=tenant, actor=owner_actor, connection=sso_connection)
    run = WorkflowRun.objects.for_tenant(tenant).get(
        workflow_id=expected_id(tenant, sso_connection)
    )
    run.status = WorkflowRun.Status.COMPLETED
    run.save(update_fields=["status"])

    with pytest.raises(Conflict):
        sync_identity_config(tenant=tenant, actor=owner_actor, connection=sso_connection)


@pytest.mark.django_db
def test_recording_the_outcome_writes_the_resource_and_starts_nothing(
    tenant: Tenant,
    owner_actor: Actor,
    sso_connection: SsoConnection,
) -> None:
    """The activity's half of the same service: what it became, on the row.

    No `recorded_workflow_starts` and no `transaction=True` here, deliberately:
    if this branch started a run it would need both, so the test failing to even
    reach a Temporal client is itself the assertion.

    **The count is a delta and not a zero since W2-R5**: creating a connection
    now asks for its own materialisation (ADR ident-6), so the fixture arrives
    with one run already recorded. What this pins is that the *outcome* branch
    adds none — which is what keeps the activity from re-entering the workflow
    that is running it.
    """
    before = WorkflowRun.objects.filter(type=SYNC_IDENTITY_CONFIG_WORKFLOW).count()
    applied = IdentityConfigApplied(
        kind=KIND_SSO_CONNECTION,
        key=str(sso_connection.pk),
        resource_id="387100000000000001",
        created=True,
    )

    sync_identity_config(
        tenant=tenant, actor=owner_actor, connection=sso_connection, applied=applied
    )

    sso_connection.refresh_from_db()
    assert sso_connection.zitadel_idp_id == "387100000000000001"
    assert sso_connection.sync_state == SsoConnection.SyncState.APPLIED
    assert WorkflowRun.objects.filter(type=SYNC_IDENTITY_CONFIG_WORKFLOW).count() == before


@pytest.mark.django_db
def test_a_member_may_not_configure_identity(
    tenant: Tenant,
    member_actor: Actor,
    sso_connection: SsoConnection,
) -> None:
    """The same wall `update_sso_connection` stands behind, on the new verb.

    A connection decides who may become a member of this tenant and at what
    role; a member who could re-point it could point it at an IdP they control.
    """
    before = sso_connection.sync_state

    with pytest.raises(Forbidden):
        sync_identity_config(tenant=tenant, actor=member_actor, connection=sso_connection)

    # Unchanged rather than `unmanaged`: since W2-R5 the owner's `create` already
    # asked for this row's materialisation, so what the refusal owes is that it
    # moved nothing — not that nothing had ever moved.
    sso_connection.refresh_from_db()
    assert sso_connection.sync_state == before


@pytest.mark.django_db
def test_an_admin_may(
    recorded_workflow_starts: None,
    tenant: Tenant,
    admin_actor: Actor,
    sso_connection: SsoConnection,
) -> None:
    """The other half: `Forbidden` for everyone would be a passing test and a broken product."""
    synced = sync_identity_config(
        tenant=tenant, actor=admin_actor, connection=sso_connection, applied=None
    )
    assert synced.sync_state == SsoConnection.SyncState.PENDING


@pytest.mark.django_db
def test_another_tenants_connection_is_not_reachable_through_this_tenant(
    tenant: Tenant,
    other_tenant: Tenant,
    other_sso_connection: SsoConnection,
) -> None:
    """The sibling that makes the tenancy claim able to fail.

    The service is handed a row, so what keeps one tenant out of another's
    identity configuration is the read that produced it: every door resolves a
    connection through `for_tenant`, and Globex's connection is simply not in
    Acme's queryset. Asserting it here rather than only in a door test is what
    makes the property survive the next door being added.
    """
    assert other_sso_connection.tenant_id == other_tenant.pk
    assert not SsoConnection.objects.for_tenant(tenant).filter(pk=other_sso_connection.pk).exists()
    assert (
        SsoConnection.objects.for_tenant(other_tenant).filter(pk=other_sso_connection.pk).exists()
    )
