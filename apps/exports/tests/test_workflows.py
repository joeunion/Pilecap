"""One request is one run, and a failed run leaves nothing that looks done.

`WorkflowEnvironment.start_time_skipping()` gives a real Temporal server, the
real worker assembly, the real interceptors and the real activities writing to
the real database. What is proved here is the part no diff shows:

* asking for an export **starts the run** — on the commit, with the
  deterministic id the row implies, from the service and not from a door;
* the activity restores the tenant and the hat off the workflow's headers,
  builds the archive and closes the row through a service;
* the run's own `WorkflowRun` row is **closed** (house rule 28) either way;
* a **planted mid-walk failure** leaves the export `failed` with the activity's
  own complaint on it, no artifact key, and no half-built object offered to
  anybody — and asking again produces a complete archive.

`transaction=True` throughout: the activities run on worker threads with their
own connections, and an `on_commit` hook only fires on a real commit.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import pytest
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowFailureError
from temporalio.testing import WorkflowEnvironment

from apps.core.actor import actor_for, system_actor
from apps.core.asyncdb import run_db
from apps.core.audit import AuditEntry
from apps.core.exceptions import Invalid
from apps.core.services import create_organization, create_tenant, root_organization
from apps.exports import activities as export_activities
from apps.exports.models import Export
from apps.exports.services import create_export, finish_export
from apps.exports.types import ExportBuilt
from apps.files import storage as files_storage
from apps.files.models import FileVersion, StoredFile
from apps.files.services import store_bytes
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker
from apps.workflows.models import WorkflowRun
from apps.workflows.services import workflow_id

from .conftest import archive_bytes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.models import Tenant

pytestmark = pytest.mark.django_db(transaction=True)


def export_run_id(tenant: Tenant, export: Export) -> str:
    """The id `create_export` will have used — DERIVED, never remembered.

    House rule 18: a workflow id is built by `workflow_id()` from the row, so a
    retried service starts one run rather than two, and a test that stored the
    id it saw could not tell a deterministic id from a lucky one.
    """
    return workflow_id(tenant=tenant, app="exports", noun="export", key=str(export.pk))


async def _local_client(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> Client:
    """Point everything at the test server, including the on-commit hook.

    The hook runs in whichever thread committed, on its own event loop, and
    dials a client of its own — exactly as it does in production. Here that dial
    has to reach the test environment rather than a dev server.
    """
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> Client:
        return attach_interceptors(await Client.connect(target, namespace=namespace))

    monkeypatch.setattr(client_module, "get_client", connect)
    return attach_interceptors(env.client)


@pytest.fixture
def small_world(db: None) -> Any:
    """A tenant, a root, an owner and one widget — enough for a real archive.

    Built here rather than out of `conftest.World` because these tests are
    `transaction=True` and asynchronous: every row has to be written through
    `run_db` from inside the test, and a synchronous fixture would have written
    it on a connection the worker threads cannot see.
    """
    from apps.accounts.services import create_user
    from apps.core.actor import actor_for
    from apps.core.models import Membership
    from apps.core.services import add_membership

    tenant = create_tenant(name="Acme", slug="acme", actor=system_actor())
    root = root_organization(tenant=tenant)
    owner = create_user(email="wf-owner@acme.com", password="a" * 24)
    add_membership(
        user=owner,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.OWNER,
        actor=system_actor(tenant=tenant),
    )
    return tenant, root, owner, actor_for(user=owner, tenant=tenant, org=root)


@pytest.mark.asyncio
async def test_asking_for_an_export_starts_one_run_that_builds_it_and_closes_its_row(
    small_world: Any, monkeypatch: pytest.MonkeyPatch, archive_bucket: str
) -> None:
    """The happy arc, end to end, with rule 28's row closed at the end of it."""
    tenant, root, _owner, actor = small_world

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        # The worker polls the queue the service will start the run on — the
        # deployment's own, from settings. Nothing here names a queue by hand.
        async with build_worker(client):
            export = await run_db(
                create_export, tenant=tenant, actor=actor, scope=Export.Scope.TENANT
            )
            handle = client.get_workflow_handle(
                export_run_id(tenant, export), result_type=ExportBuilt
            )
            built: ExportBuilt = await handle.result()
            described = await handle.describe()

    assert described.status == WorkflowExecutionStatus.COMPLETED
    assert built.export_id == str(export.pk)
    assert built.rows > 0

    finished = await run_db(lambda: Export.objects.for_tenant(tenant).get(pk=export.pk))
    assert finished.status == Export.Status.COMPLETED
    assert finished.artifact_key
    assert finished.artifact_bytes > 0
    assert finished.completed_at is not None
    assert finished.manifest["rows"] == built.rows

    # House rule 28: the ledger does not lie by omission.
    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).filter(type="ExportTenantDataWorkflow").get()
    )
    assert run.workflow_id == export_run_id(tenant, export)
    assert run.status == WorkflowRun.Status.COMPLETED
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_the_same_idempotency_key_twice_is_one_row_and_one_run(
    small_world: Any, monkeypatch: pytest.MonkeyPatch, archive_bucket: str
) -> None:
    """A retry of a request nobody saw the answer to must not be a second archive.

    Which matters more here than almost anywhere: a second run is a second
    complete copy of somebody's database in a bucket, charged to them, kept for
    a month, and invisible unless somebody counts.
    """
    tenant, _root, _owner, actor = small_world

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            first = await run_db(
                create_export, tenant=tenant, actor=actor, idempotency_key="nightly"
            )
            second = await run_db(
                create_export, tenant=tenant, actor=actor, idempotency_key="nightly"
            )
            await client.get_workflow_handle(
                export_run_id(tenant, first), result_type=ExportBuilt
            ).result()

    assert second.pk == first.pk
    assert await run_db(lambda: Export.objects.for_tenant(tenant).count()) == 1
    assert (
        await run_db(
            lambda: (
                WorkflowRun.objects.for_tenant(tenant)
                .filter(type="ExportTenantDataWorkflow")
                .count()
            )
        )
        == 1
    )


@pytest.mark.asyncio
async def test_a_failure_mid_walk_leaves_a_failed_row_with_no_artifact_on_it(
    small_world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half, and the one that matters to whoever is waiting.

    Planted inside the archive writer, so everything before it has already run:
    the row is `running`, the walk is under way, and then it dies. What must be
    true afterwards is that the row says `failed` with the ACTIVITY'S OWN
    complaint on it — not Temporal's "Activity task failed" — and that
    `artifact_key` is blank, because a key pointing at a half-written object is
    an archive a customer would download, open, and find short.
    """
    tenant, _root, _owner, actor = small_world

    def explode(**_: Any) -> None:
        raise RuntimeError("the bucket went away mid-walk")

    monkeypatch.setattr(export_activities, "_write_the_archive", explode)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            export = await run_db(create_export, tenant=tenant, actor=actor)
            handle = client.get_workflow_handle(export_run_id(tenant, export))
            # `WorkflowFailureError`, whose own message is "Workflow execution
            # failed" — which is exactly the wrapper the row must NOT carry, and
            # the assertion below is where that is checked.
            with pytest.raises(WorkflowFailureError):
                await handle.result()
            described = await handle.describe()

    assert described.status == WorkflowExecutionStatus.FAILED

    failed = await run_db(lambda: Export.objects.for_tenant(tenant).get(pk=export.pk))
    assert failed.status == Export.Status.FAILED
    assert failed.artifact_key == "", "a failed run must offer no partial archive"
    assert failed.is_downloadable is False
    assert "the bucket went away mid-walk" in failed.error, (
        "the row carries the activity's own complaint, not the wrapper's \"Activity task failed\""
    )

    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).filter(type="ExportTenantDataWorkflow").get()
    )
    assert run.status == WorkflowRun.Status.FAILED
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_asking_again_after_a_failure_produces_a_complete_archive(
    small_world: Any, monkeypatch: pytest.MonkeyPatch, archive_bucket: str
) -> None:
    """The activities are idempotent, so the retry is an ordinary second request.

    A new request rather than a re-run of the old one, deliberately: the failed
    export stays failed and readable, because "what happened to the one I asked
    for on Tuesday" is a question a support conversation turns on.
    """
    tenant, _root, _owner, actor = small_world

    broken = {"yes": True}
    real = export_activities._write_the_archive

    def sometimes(**kwargs: Any) -> Any:
        if broken["yes"]:
            raise RuntimeError("the bucket went away mid-walk")
        return real(**kwargs)

    monkeypatch.setattr(export_activities, "_write_the_archive", sometimes)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            first = await run_db(create_export, tenant=tenant, actor=actor)
            with pytest.raises(WorkflowFailureError):
                await client.get_workflow_handle(export_run_id(tenant, first)).result()

            broken["yes"] = False
            second = await run_db(create_export, tenant=tenant, actor=actor)
            built: ExportBuilt = await client.get_workflow_handle(
                export_run_id(tenant, second), result_type=ExportBuilt
            ).result()

    assert second.pk != first.pk
    assert built.rows > 0

    rows = await run_db(
        lambda: {
            str(one.pk): (one.status, one.artifact_key)
            for one in Export.objects.for_tenant(tenant).all()
        }
    )
    assert rows[str(first.pk)][0] == Export.Status.FAILED
    assert rows[str(first.pk)][1] == ""
    assert rows[str(second.pk)][0] == Export.Status.COMPLETED
    assert rows[str(second.pk)][1]


@pytest.mark.asyncio
async def test_the_run_reads_as_the_hat_it_was_started_under(
    small_world: Any, monkeypatch: pytest.MonkeyPatch, archive_bucket: str
) -> None:
    """The acting hat rides the headers, so a branch's export is a branch's archive.

    The activity that runs a minute later has no request to read `X-Org` from.
    If the hat did not travel it would act for the whole tenant, and a branch
    manager's export would quietly become the customer's whole database — which
    is the leak the hat exists to close and would be invisible in a diff.
    """
    tenant, root, owner, actor = small_world
    from apps.core.actor import actor_for

    branch = await run_db(
        create_organization,
        tenant=tenant,
        parent=root,
        name="Branch",
        slug="branch",
        actor=actor,
    )
    branch_actor = actor_for(user=owner, tenant=tenant, org=branch)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            export = await run_db(
                create_export,
                tenant=tenant,
                actor=branch_actor,
                scope=Export.Scope.ORGANIZATION,
            )
            await client.get_workflow_handle(
                export_run_id(tenant, export), result_type=ExportBuilt
            ).result()

    finished = await run_db(lambda: Export.objects.for_tenant(tenant).get(pk=export.pk))
    assert finished.manifest["organization"]["slug"] == "branch"
    assert finished.manifest["scope"] == Export.Scope.ORGANIZATION


# --- XPr: the supersession, proven at the far end of a real run ---------------


@pytest.mark.asyncio
async def test_the_archive_lands_under_the_files_grammar_and_never_the_retired_one(
    small_world: Any, monkeypatch: pytest.MonkeyPatch, archive_bucket: str
) -> None:
    """The retired key grammar is DEAD, and the new one is what a real run produces.

    Before XPr this app built its own key — `core.storage.tenant_prefixed_key`,
    `"tenants/<slug>/<uuid>-<name>"` — which quotes a tenant SLUG and a
    FILENAME, both renamable, both re-issuable, and which ADR files-2 rules
    against. F1 recorded the contradiction as a SUPERSESSION rather than a
    promotion; this is the assertion that it actually happened.

    Both directions, because either alone is weak: the new grammar is asserted
    by CONSTRUCTION (`files.storage.version_key` rebuilt from the row's own
    parts, so the day the grammar moves this test moves with it rather than
    pinning a string), and the old one is asserted ABSENT — nothing under
    `tenants/` anywhere in the bucket, which is what makes "dead" a measurement
    rather than a claim about the diff.
    """
    tenant, _root, _owner, actor = small_world

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            export = await run_db(
                create_export, tenant=tenant, actor=actor, scope=Export.Scope.TENANT
            )
            await client.get_workflow_handle(
                export_run_id(tenant, export), result_type=ExportBuilt
            ).result()

    finished = await run_db(lambda: Export.objects.for_tenant(tenant).get(pk=export.pk))
    version = await run_db(lambda: FileVersion.objects.get(pk=_the_artifact(finished)))

    # The new grammar, rebuilt rather than spelled.
    assert finished.artifact_key == files_storage.version_key(
        tenant=tenant, file_pk=version.file_id, version=version.version
    )
    assert finished.artifact_key.startswith(f"t/{tenant.pk}/f/")
    # The retired one, absent from the whole bucket rather than from this row.
    everything = await run_db(lambda: sorted(_keys_in_the_bucket()))
    assert everything, "the bucket is empty, so 'no legacy keys' would be vacuous"
    assert not [key for key in everything if key.startswith("tenants/")], (
        f"an archive landed under the retired slug-and-filename grammar: {everything}"
    )
    assert tenant.slug not in " ".join(everything), "a key still quotes a renamable slug"


@pytest.mark.asyncio
async def test_the_archive_reads_back_through_the_files_seam_with_the_digest_it_recorded(
    small_world: Any, monkeypatch: pytest.MonkeyPatch, archive_bucket: str
) -> None:
    """What the row says about the bytes is what the store holds. **Measured, both ends.**

    The whole reason the artifact reference moved onto the files blob model
    (the fourth re-point item) is that a departing customer verifying an
    archive months later needs a digest with provenance. This drives a real run,
    reads the object back out of the store, and hashes it — so `sha256` on the
    row is a claim about bytes somebody can check rather than a column that gets
    written.

    It also pins the SIZE from three directions — the version row, the store's
    own `HEAD`, and the length of what came back — because a truncating store is
    exactly the failure a recorded digest exists to catch.
    """
    tenant, _root, _owner, actor = small_world

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            export = await run_db(
                create_export, tenant=tenant, actor=actor, scope=Export.Scope.TENANT
            )
            await client.get_workflow_handle(
                export_run_id(tenant, export), result_type=ExportBuilt
            ).result()

    finished = await run_db(lambda: Export.objects.for_tenant(tenant).get(pk=export.pk))
    version = await run_db(lambda: FileVersion.objects.get(pk=_the_artifact(finished)))
    body = await run_db(lambda: archive_bytes(str(finished.artifact_key)))
    head = await run_db(lambda: files_storage.head(tenant=tenant, key=str(finished.artifact_key)))

    assert body[:2] == b"PK", "that is a zip"
    assert hashlib.sha256(body).hexdigest() == version.sha256, (
        "the recorded digest is not the digest of what the store holds"
    )
    assert len(body) == version.size_bytes == head.size_bytes == finished.artifact_bytes
    assert version.status == FileVersion.Status.STORED
    # And the row reads its own provenance without anybody joining by hand.
    assert await run_db(lambda: finished.artifact_sha256) == version.sha256


@pytest.mark.asyncio
async def test_the_archive_is_filed_under_the_person_who_asked_for_it(
    small_world: Any, monkeypatch: pytest.MonkeyPatch, archive_bucket: str
) -> None:
    """THE ACTOR THREADS. `uploaded_by` is the requester, restored off the headers.

    F2's declared frontier — `store_bytes`/`store_stream` needs a PERSON, and a
    schedule-started run cannot call them — meets its first customer here. The
    export build is service-started, so `create_export` stamps the acting user on
    the workflow's Temporal headers and `workflow_context()` hands it back inside
    the activity; `_person_for` turns that into the actor the document is filed
    under.

    **Two actors, and the pair is the claim** (see `_person_for`): the export's
    own audit rows say the SYSTEM built the archive, because nobody clicked it,
    and the file's `uploaded_by` says WHOSE it is, because a document always
    answers that. This asserts the second and the sibling test below asserts
    they have not been collapsed into one.
    """
    tenant, _root, owner, actor = small_world

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            export = await run_db(
                create_export, tenant=tenant, actor=actor, scope=Export.Scope.TENANT
            )
            await client.get_workflow_handle(
                export_run_id(tenant, export), result_type=ExportBuilt
            ).result()

    finished = await run_db(lambda: Export.objects.for_tenant(tenant).get(pk=export.pk))
    version = await run_db(
        lambda: FileVersion.objects.select_related("file").get(pk=_the_artifact(finished))
    )

    assert version.uploaded_by_id == owner.pk, "the archive was filed under nobody"
    assert version.file.uploaded_by_id == owner.pk
    assert version.file.purpose == StoredFile.Purpose.EXPORT
    # The document landed where the export did — the acting hat, never the root
    # by accident (ADR core-20, and `FileVersion.derive_org_from`).
    assert version.file.organization_id == finished.organization_id
    assert version.organization_id == finished.organization_id


@pytest.mark.asyncio
async def test_the_run_is_audited_as_the_system_even_though_the_file_names_a_person(
    small_world: Any, monkeypatch: pytest.MonkeyPatch, archive_bucket: str
) -> None:
    """The other half of the split, so the two actors cannot be quietly collapsed.

    `_actor_for` refuses to attribute an overnight walk to whoever asked for it
    last week, and XPr did not repeal that — it added a SECOND actor for a second
    question. If somebody later 'simplifies' the activity by threading the person
    everywhere, this is the test that says so: `exports.finish_export` is audited
    with `actor_kind` system, while the file the same activity produced names the
    person.
    """
    tenant, _root, owner, actor = small_world

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            export = await run_db(
                create_export, tenant=tenant, actor=actor, scope=Export.Scope.TENANT
            )
            await client.get_workflow_handle(
                export_run_id(tenant, export), result_type=ExportBuilt
            ).result()

    finish = await run_db(
        lambda: (
            AuditEntry.objects.for_tenant(tenant)
            .filter(action="exports.finish_export")
            .latest("created_at")
        )
    )
    assert finish.actor_kind == AuditEntry.Kind.SYSTEM
    assert finish.actor_user_id is None, "the walk was attributed to a person who did not do it"

    finished = await run_db(lambda: Export.objects.for_tenant(tenant).get(pk=export.pk))
    version = await run_db(lambda: FileVersion.objects.get(pk=_the_artifact(finished)))
    assert version.uploaded_by_id == owner.pk


def test_an_artifact_from_another_branch_is_refused_on_this_export(
    small_world: Any, archive_bucket: str, recorded_workflow_starts: None
) -> None:
    """The belt rule 26's reachability clause on `finish_export` promises. **Planted.**

    `finish_export` takes a `FileVersion` and rule 26 asks what stops it being
    somebody else's. The answer is not `may_be_named` — the actor there is the
    system, for which that question cannot fail — so the service asks the
    question that CAN: does this artifact belong to the same part of the network
    as the export it is being recorded on.

    Written because the guard was added with nothing able to fail it: removing
    the refusal left every test in this file green, which is a guard that is a
    sentence. This is the test that makes it a claim. Without it, a version filed
    for one branch could be recorded on another branch's export — a row pointing
    at bytes its own readers cannot see under `visible_to`, and a purge that
    reads the tenant off the wrong row.
    """
    tenant, root, owner, actor = small_world
    sibling = create_organization(
        tenant=tenant, parent=root, name="Elsewhere", slug="elsewhere", actor=actor
    )
    export = create_export(tenant=tenant, actor=actor, scope=Export.Scope.TENANT)
    # An artifact filed under a DIFFERENT hat, by the same person — which is the
    # realistic shape of the mistake: not an attack, a mis-threaded actor.
    foreign = store_bytes(
        tenant=tenant,
        actor=actor_for(user=owner, tenant=tenant, org=sibling),
        filename="somebody-elses.zip",
        content_type="application/zip",
        content=b"PK\x05\x06" + b"\x00" * 18,
        purpose=StoredFile.Purpose.EXPORT,
    )
    assert foreign.organization_id != export.organization_id, "the plant did not plant"

    with pytest.raises(Invalid) as refused:
        finish_export(
            tenant=tenant,
            actor=export_activities._actor_for(export),
            export=export,
            version=foreign,
            manifest={"version": 1, "rows": 0, "models": []},
        )

    assert "different tenant or organization" in str(refused.value.errors["version"])
    export.refresh_from_db()
    assert export.status == Export.Status.PENDING, "a refused finish must record nothing"
    assert export.artifact_key == ""
    assert export.artifact_version_id is None


def _keys_in_the_bucket() -> list[str]:
    """Every key in this checkout's bucket right now. A test's own listing."""
    client = files_storage.client()
    found: list[str] = []
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=files_storage.bucket_name()
    ):
        found.extend(str(entry["Key"]) for entry in page.get("Contents", []))
    return found


def _the_artifact(export: Export) -> Any:
    """The artifact version's id, refused rather than narrowed.

    `artifact_version` is nullable — `SET_NULL`, so the files app can sweep its
    own rows — and every caller here has just driven a run to completion, so a
    null is a broken build rather than a case to handle. Saying so once beats
    four `assert ... is not None` lines that read like type appeasement.
    """
    assert export.artifact_version_id is not None, "the finished run recorded no artifact"
    return export.artifact_version_id
