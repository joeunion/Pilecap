"""This app's durable halves, against a real Temporal and a real MinIO.

Four things are proved here that no diff shows:

* **the arc**: a client PUTs bytes on a presigned URL, confirms, and a run it
  never sees heads the object, streams it, measures it and writes down what it
  measured — with the `WorkflowRun` row **closed** at the end (house rule 28,
  the `record_run` half: a service started this run, so somebody is waiting on a
  visibility row, and a row left saying `running` beside a finished execution is
  a row that lies);
* **the retry**, driven at the activity boundary where Temporal drives it: the
  same activity called twice records **one** `UsageEntry`. This is the live case
  `apps/usage`'s same-key replay semantics exist for;
* **the failure**: a confirm for an upload that never happened fails the run,
  leaves the version `PENDING` for the sweep, meters nothing, and puts the
  STORE's own complaint on the row rather than Temporal's "Activity task
  failed";
* **the sweep**: the row that failure left is expired through the DECLARED
  SCHEDULE'S OWN PATH — the declaration's workflow, its argument and its
  deterministic id, started the way `run_declared_machinery` starts it — and the
  document it empties is archived with `door=workflow` on the audit row. What is
  simulated, and what is not, is spelled out on the test itself.

`transaction=True` throughout the durable tests: the activities run on worker
threads with their own connections, and an `on_commit` hook only fires on a real
commit.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowFailureError
from temporalio.testing import WorkflowEnvironment

from apps.core.actor import actor_for
from apps.core.asyncdb import run_db
from apps.core.audit import AuditEntry
from apps.core.time import now
from apps.files import activities, services, storage
from apps.files.meters import STORAGE_BYTES
from apps.files.models import PENDING_UPLOAD_TTL_HOURS, FileVersion, StoredFile
from apps.files.types import FinalizeUpload, StoreMeasurement
from apps.files.workflows import VERIFY_RETRY
from apps.usage.models import UsageEntry
from apps.workflows import client as client_module
from apps.workflows.client import (
    attach_interceptors,
    build_worker,
    declared_start,
    start_declared_run,
    task_queue,
)
from apps.workflows.context import reset_principal, set_principal
from apps.workflows.models import WorkflowRun
from apps.workflows.services import workflow_id

from .conftest import make_version

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator

    from apps.accounts.models import User
    from apps.core.models import Organization, Tenant

pytestmark = pytest.mark.django_db(transaction=True)

BODY = b"a document somebody will want back\n" * 128

#: What a client MUST send on an upload URL from this seam. Both headers are
#: inside the SigV4 signature (`storage.presign_put`), so a PUT that drops either
#: is refused by the store before a byte lands.
UPLOAD_HEADERS = {
    "Content-Type": "application/pdf",
    "If-None-Match": storage.OVERWRITE_NOTHING,
}


@contextmanager
def acting_as(tenant: Tenant, user: User, org: Organization) -> Iterator[None]:
    """The principal the inbound interceptor would have unpacked from the headers.

    Set by hand because there is no worker in the activity-level tests. It is the
    same three values `workflow_context()` reads and nothing else — an activity
    that could take the tenant as an argument would be an activity a caller could
    point at somebody else's data.
    """
    tokens = set_principal(tenant_id=str(tenant.pk), user_id=str(user.pk), org_id=str(org.pk))
    try:
        yield
    finally:
        reset_principal(tokens)


async def _local_client(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> Client:
    """Point everything at the test server, including the on-commit hook.

    The hook runs in whichever thread committed, on its own event loop, and dials
    a client of its own — exactly as it does in production. Here that dial has to
    reach the test environment rather than a dev server.
    """
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> Client:
        return attach_interceptors(await Client.connect(target, namespace=namespace))

    monkeypatch.setattr(client_module, "get_client", connect)
    return attach_interceptors(env.client)


def _upload(ticket: Any, content: bytes = BODY) -> None:
    """Put the bytes where the ticket says, the way a browser would.

    Through the presigned URL and never through Django, which is the design being
    exercised rather than described.
    """
    put = httpx.put(ticket.upload_url, content=content, headers=UPLOAD_HEADERS, timeout=30)
    assert put.status_code == 200, put.text


def _filed(tenant: Tenant, owner: User, org: Organization) -> Any:
    """A document with version 1 allocated and its bytes uploaded, ready to confirm."""
    ticket = services.create_file(
        tenant=tenant,
        actor=actor_for(user=owner, tenant=tenant, org=org),
        filename="contract.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )
    return ticket


# --- the retry, at the boundary Temporal retries -----------------------------


def test_the_activity_run_twice_records_one_usage_entry(
    tenant: Tenant, root_org: Organization, owner: User, bucket: str
) -> None:
    """**ADR files-2, criterion 3, proved by a doubled activity call.**

    Temporal guarantees an activity runs AT LEAST once: a worker that commits and
    then dies before reporting completion gets the whole activity again. So the
    thing that must not double is the money, and the thing that makes it not
    double is that the meter's idempotency key is derived from the version's own
    primary key rather than minted per call.

    Both activities are driven here exactly as the worker drives them — the real
    functions, the real principal in the context, the real service, the real
    ledger — twice each. `verify_object` writes nothing at all, so its second run
    is free; `record_stored` re-asserts the same row and the ledger recognises
    the replay.
    """
    ticket = _filed(tenant, owner, root_org)
    _upload(ticket)

    with acting_as(tenant, owner, root_org):
        first = activities.verify_object(FinalizeUpload(version_id=str(ticket.version.pk)))
        again = activities.verify_object(FinalizeUpload(version_id=str(ticket.version.pk)))
        measurement = StoreMeasurement(
            version_id=str(ticket.version.pk),
            sha256=first.sha256,
            size_bytes=first.size_bytes,
        )
        activities.record_stored(measurement)
        activities.record_stored(measurement)

    assert first == again
    assert first.size_bytes == len(BODY)
    assert first.head_size_bytes == len(BODY)

    stored = FileVersion.objects.get(pk=ticket.version.pk)
    assert stored.status == FileVersion.Status.STORED
    assert stored.sha256 == first.sha256

    entries = list(UsageEntry.objects.filter(tenant=tenant, meter=STORAGE_BYTES))
    assert len(entries) == 1
    assert entries[0].quantity == Decimal(len(BODY))


def test_what_is_metered_is_what_the_store_holds_and_not_what_was_declared(
    tenant: Tenant, root_org: Organization, owner: User, bucket: str
) -> None:
    """The archive-vs-database agreement, extended to the number that costs money.

    The client declares one size at `create_file` and uploads a different number
    of bytes — which is not exotic, it is what a truncated upload, a retried
    browser and a lying client all look like. What is recorded and what is
    metered is the count that came off the wire while we streamed the object
    back, and the object in the bucket agrees with the row.
    """
    ticket = services.create_file(
        tenant=tenant,
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
        filename="contract.pdf",
        content_type="application/pdf",
        size_bytes=9,
        purpose=StoredFile.Purpose.UPLOAD,
    )
    _upload(ticket, content=BODY)

    with acting_as(tenant, owner, root_org):
        measured = activities.verify_object(FinalizeUpload(version_id=str(ticket.version.pk)))
        activities.record_stored(
            StoreMeasurement(
                version_id=str(ticket.version.pk),
                sha256=measured.sha256,
                size_bytes=measured.size_bytes,
            )
        )

    stored = FileVersion.objects.get(pk=ticket.version.pk)
    in_the_bucket = storage.sha256_of(tenant=tenant, key=stored.key)
    entry = UsageEntry.objects.get(tenant=tenant, meter=STORAGE_BYTES)

    assert stored.size_bytes == len(BODY) != 9
    assert stored.sha256 == in_the_bucket.sha256
    assert entry.quantity == Decimal(in_the_bucket.size_bytes)


# --- the durable arc ----------------------------------------------------------


@pytest.mark.asyncio
async def test_confirming_an_upload_finalizes_it_and_closes_the_run(
    tenant: Tenant,
    root_org: Organization,
    owner: User,
    bucket: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole arc, once, end to end, with rule 28's row closed at the end of it.

    Nothing here streams bytes through Django: they go up on a presigned PUT and
    come back down through the storage seam inside the activity, which is the
    design being proven rather than described.
    """
    ticket = await run_db(_filed, tenant, owner, root_org)
    _upload(ticket)
    expected = workflow_id(tenant=tenant, app="files", noun="version", key=str(ticket.version.pk))

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            await run_db(
                services.confirm_upload,
                tenant=tenant,
                actor=actor_for(user=owner, tenant=tenant, org=root_org),
                version=ticket.version,
                idempotency_key="browser-1",
            )
            handle = client.get_workflow_handle(expected)
            await handle.result()
            described = await handle.describe()

    assert described.status == WorkflowExecutionStatus.COMPLETED

    stored = await run_db(lambda: FileVersion.objects.get(pk=ticket.version.pk))
    assert stored.status == FileVersion.Status.STORED
    assert stored.size_bytes == len(BODY)
    assert await run_db(lambda: StoredFile.objects.get(pk=ticket.file.pk).current_version) == 1

    entry = await run_db(lambda: UsageEntry.objects.get(tenant=tenant, meter=STORAGE_BYTES))
    assert entry.quantity == Decimal(len(BODY))
    assert entry.organization_id == root_org.pk

    run = await run_db(lambda: WorkflowRun.objects.for_tenant(tenant).get(workflow_id=expected))
    assert run.status == WorkflowRun.Status.COMPLETED
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_confirming_an_upload_that_never_happened_fails_loudly_and_meters_nothing(
    tenant: Tenant,
    root_org: Organization,
    owner: User,
    bucket: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half, and the one that decides whether this platform can be trusted.

    A client confirms an upload it never made. What must NOT happen is a version
    marked stored over nothing — a row claiming a digest for an object that does
    not exist would be a lie the audit trail carries forever, and a meter entry
    beside it would be a customer billed for bytes nobody has.

    What happens instead: the verification fails against the real store, the run
    fails, the version stays `PENDING` (which is the sweep's business, not a
    third status), nothing is metered, and the `WorkflowRun` row carries the
    STORE's own complaint rather than Temporal's "Activity task failed".
    """
    ticket = await run_db(_filed, tenant, owner, root_org)
    expected = workflow_id(tenant=tenant, app="files", noun="version", key=str(ticket.version.pk))

    # **The attempts are counted, not assumed.** `VERIFY_RETRY` says five, and
    # until this list existed nothing here could tell five attempts from one:
    # the version stays `PENDING` and the run reads `failed` either way. The
    # store still answers for real — this only records that it was asked — which
    # is what keeps "the verification fails against the real store" true.
    attempts: list[int] = []
    real_head = storage.head

    def counted_head(**kwargs: Any) -> Any:
        attempts.append(1)
        return real_head(**kwargs)

    monkeypatch.setattr(storage, "head", counted_head)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            await run_db(
                services.confirm_upload,
                tenant=tenant,
                actor=actor_for(user=owner, tenant=tenant, org=root_org),
                version=ticket.version,
                idempotency_key="browser-1",
            )
            with pytest.raises(WorkflowFailureError):
                await client.get_workflow_handle(expected).result()

    assert len(attempts) == VERIFY_RETRY.maximum_attempts == 5, (
        f"the object was headed {len(attempts)} times, not the five VERIFY_RETRY declares"
    )

    unchanged = await run_db(lambda: FileVersion.objects.get(pk=ticket.version.pk))
    assert unchanged.status == FileVersion.Status.PENDING
    assert unchanged.sha256 == ""
    assert unchanged.size_bytes is None
    assert await run_db(lambda: StoredFile.objects.get(pk=ticket.file.pk).current_version) == 0
    assert not await run_db(
        lambda: UsageEntry.objects.filter(tenant=tenant, meter=STORAGE_BYTES).exists()
    )

    run = await run_db(lambda: WorkflowRun.objects.for_tenant(tenant).get(workflow_id=expected))
    assert run.status == WorkflowRun.Status.FAILED
    assert run.finished_at is not None
    # The activity's own complaint, walked out of the cause chain — not the
    # wrapper's "Activity task failed", which is true and useless.
    assert "Activity task failed" != run.error
    assert "404" in run.error or "NoSuchKey" in run.error or "Not Found" in run.error


# --- the declared sweep, driven rather than declared ---------------------------


def _abandoned(tenant: Tenant, owner: User, org: Organization) -> tuple[StoredFile, FileVersion]:
    """A document whose only upload never happened, aged past the TTL.

    Planted rather than uploaded, and that is the point: this is the residue
    an earlier field test left behind — a `create_file` whose PUT never came and
    whose confirm therefore never landed — so there is no object anywhere and
    nothing for a bucket to hold. `QuerySet.update` moves `created_at`, which is
    `auto_now_add` and would not move under a `save()`.
    """
    document = StoredFile(
        tenant=tenant,
        organization=org,
        filename="never-arrived.pdf",
        purpose=StoredFile.Purpose.UPLOAD,
        uploaded_by=owner,
    )
    document.full_clean()
    document.save()
    version = make_version(file=document, version=1, uploaded_by=owner)
    FileVersion.objects.filter(pk=version.pk).update(
        created_at=now() - timedelta(hours=PENDING_UPLOAD_TTL_HOURS + 6)
    )
    return document, version


@pytest.mark.asyncio
async def test_the_declared_sweep_expires_a_pending_version_and_archives_its_document(
    tenant: Tenant,
    root_org: Organization,
    owner: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The headline, DRIVEN through the schedule's own path rather than called.

    **What "the real schedule path" means here, exactly.** The run is started by
    `apps.workflows.client.start_declared_run`, which reads the app's
    `ScheduleDeclaration`, takes the workflow name, the argument and the
    deterministic id off the `Schedule` value the app declared, and starts THAT
    — the same function `run_declared_machinery` calls on every tick in this
    deployment's own lifetime class (`process`; ADR platform-lifecycle-1). So
    everything below the schedule is real: the declared window, the declared id,
    the registered workflow, the discovered worker, the activity interceptor that
    stamps `door=workflow`, the service, the transaction, the audit rows and the
    event.

    What is NOT real is the SERVER'S TIMER, and it is named rather than implied:
    the time-skipping test server has no schedules API at all
    (`apps/workflows/tests/test_reconciler.py` records the same limitation), so
    nothing here can wait for a Temporal Schedule to fire. The two lifetime
    classes read the same declaration through `declared_start`, which is what
    makes driving one of them evidence about the machine rather than about one
    environment; the `deployment` class's own create-or-update is proved in
    `apps/workflows/tests/test_machinery_lifetime.py`.

    A unit call to the service would have proved none of it — not the id, not the
    argument, not the registration, and above all not `door=workflow`, which is
    the one field that says a schedule and not a person did this.
    """
    document, version = await run_db(_abandoned, tenant, owner, root_org)
    expected = declared_start(activities.SWEEP_PENDING_UPLOADS, queue=task_queue()).id

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            started = await start_declared_run(client, activities.SWEEP_PENDING_UPLOADS)
            handle = client.get_workflow_handle(started)
            await handle.result()
            described = await handle.describe()

    assert started == expected, "the declared id, not a random one (house rule 18)"
    assert described.status == WorkflowExecutionStatus.COMPLETED

    # The residue is gone — the assertion this whole rung exists for.
    assert not await run_db(lambda: FileVersion.objects.filter(pk=version.pk).exists())

    # ...and the document it emptied has left the working set.
    archived = await run_db(lambda: StoredFile.objects.get(pk=document.pk))
    assert archived.archived_at is not None

    # The audit trail says a WORKFLOW did it, which is the field a unit call
    # could never have produced — the activity interceptor binds it, and nothing
    # in the service knows the word.
    row = await run_db(
        lambda: AuditEntry.objects.for_tenant(tenant).get(
            action="files.archive_emptied_file", object_id=document.pk
        )
    )
    assert row.door == "workflow"
    assert row.actor_kind == AuditEntry.Kind.SYSTEM
    assert row.acting_org_id == root_org.pk, "the document's own hat, not the root by default"

    # And the deployment's own row for the sweep itself, in the platform
    # population (tenant=None) — a sweep that left no record cannot be told from
    # one that never fired.
    swept = await run_db(
        lambda: AuditEntry.objects.for_platform().get(action="files.purge_pending_versions")
    )
    assert swept.door == "workflow"
    assert swept.outcome == AuditEntry.Outcome.OK
