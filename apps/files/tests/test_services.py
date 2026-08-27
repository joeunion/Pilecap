"""The upload verbs, and **the meter that is `apps/usage`'s first real customer**.

What is proved here, in the order the criteria ask for it:

* a document lands at the **acting hat and never the root** (ADR core-20), with
  version 1 `PENDING` and `current_version` 0 — a real state, not a placeholder;
* **replace is additive**: version n is untouched, still keyed, still true;
* an upload URL is minted for a `PENDING` version and **refused for a stored
  one** — the service-side fence the `If-None-Match` belt stands beside;
* **the digest and the size are OURS**: what is recorded is what the store
  handed back, and a caller's declared size never reaches a column;
* **THE HEADLINE — a retried finalize records ONE `UsageEntry`.** Temporal
  guarantees an activity runs at least once; the meter's idempotency key is
  derived from the version's primary key and the meter name, so the replay is
  recognised inside the caller's own transaction and nobody is billed twice for
  one document. Proved by driving the service twice, and proved red first by
  severing exactly that derivation;
* the ledger's OTHER ratified half is live here too: a retry that arrives with a
  **different** quantity is refused, and the transaction that carried it rolls
  back rather than leaving a digest the ledger disagrees with;
* promotion is **upward only**, both orders driven;
* `store_bytes` measures what the store holds rather than counting what it sent,
  so the generation path and the upload path record their digests through one
  instrument.
"""

from __future__ import annotations

import hashlib
import threading
from decimal import Decimal
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import pytest
from django.db import connection

from apps.core.actor import actor_for, system_actor
from apps.core.exceptions import Conflict, Invalid, NotFound
from apps.core.models import Membership, Organization
from apps.core.services import add_membership, create_organization
from apps.events.models import Event
from apps.files import services, storage
from apps.files.events import FILE_STORED
from apps.files.meters import STORAGE_BYTES
from apps.files.models import FileVersion, StoredFile
from apps.usage.models import UsageEntry
from apps.usage.services import record_usage
from apps.workflows.models import WorkflowRun
from apps.workflows.services import workflow_id

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User
    from apps.core.actor import Actor
    from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

#: A body big enough that the digest is not a coincidence and small enough that
#: the suite does not notice it.
BODY = b"the bytes we actually hold\n" * 64
DIGEST = hashlib.sha256(BODY).hexdigest()


@pytest.fixture(autouse=True)
def _a_bucket_is_configured(named_bucket: str) -> None:
    """Every service here mints a URL, and a URL needs a bucket NAME.

    The name and not the bucket: `presign_put` reaches no store, so a test whose
    subject is a service should not pay two MinIO round trips per case. The three
    tests that actually move bytes ask for `bucket` as well, which creates the
    real one — and sets the same name, so the two never disagree.
    """


def _measured(version: FileVersion, actor: Actor, tenant: Tenant, **overrides: Any) -> FileVersion:
    """Drive `record_stored` the way the activity does, with a real measurement.

    The defaults are BODY's own digest and length, so a test that says nothing
    about the numbers is still recording a measurement that could have come off
    a wire rather than one invented to make an assertion pass.
    """
    payload: dict[str, Any] = {"sha256": DIGEST, "size_bytes": len(BODY)}
    payload.update(overrides)
    return services.record_stored(tenant=tenant, actor=actor, version=version, **payload)


def _entries(tenant: Tenant) -> list[UsageEntry]:
    return list(UsageEntry.objects.filter(tenant=tenant, meter=STORAGE_BYTES))


def _stored_events(tenant: Tenant) -> list[Event]:
    return list(Event.objects.filter(tenant=tenant, name=FILE_STORED))


# --- creating, and where it lands --------------------------------------------


def test_a_new_document_lands_at_the_acting_hat_with_a_pending_first_version(
    tenant: Tenant, root_org: Organization, owner_actor: Actor
) -> None:
    """ADR core-20's placement law, and the two-row shape underneath it.

    There is no `organization=` parameter to get wrong: the hat decides, so the
    only way a document lands somewhere is that somebody was standing there.
    """
    ticket = services.create_file(
        tenant=tenant,
        actor=owner_actor,
        filename="invoice.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )

    assert ticket.file.organization_id == root_org.pk
    assert ticket.file.current_version == 0
    assert ticket.version.version == 1
    assert ticket.version.status == FileVersion.Status.PENDING
    assert ticket.version.organization_id == root_org.pk
    assert ticket.version.key == storage.version_key(
        tenant=tenant, file_pk=ticket.file.pk, version=1
    )
    # Nothing was measured, and the columns say so honestly rather than with a
    # zero that reads like a measurement.
    assert ticket.version.size_bytes is None
    assert ticket.version.sha256 == ""


def test_the_upload_url_signs_the_overwrite_belt(tenant: Tenant, owner_actor: Actor) -> None:
    """The belt rides on every URL this service hands out, not just on the seam.

    The wire half — that MinIO refuses the replay with 412, and refuses a PUT
    that drops the header at all — is proved against a live store in
    `test_storage.py`. What this holds is that the URL the SERVICE mints is one
    of those URLs.
    """
    ticket = services.create_file(
        tenant=tenant,
        actor=owner_actor,
        filename="invoice.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )

    signed = parse_qs(urlparse(ticket.upload_url).query)["X-Amz-SignedHeaders"][0]

    assert "if-none-match" in signed
    assert "content-type" in signed


def test_a_caller_with_no_hat_is_refused_rather_than_defaulted_to_the_root(
    tenant: Tenant, owner: User
) -> None:
    """The placement law fails closed. A document at the root is everybody's."""
    hatless = actor_for(user=owner, tenant=tenant, org=None)

    with pytest.raises(Invalid) as refused:
        services.create_file(
            tenant=tenant,
            actor=hatless,
            filename="invoice.pdf",
            content_type="application/pdf",
            size_bytes=1,
            purpose=StoredFile.Purpose.UPLOAD,
        )

    assert "organization" in refused.value.errors
    assert not StoredFile.objects.filter(tenant=tenant).exists()


def test_a_declared_size_above_the_ceiling_is_refused_before_a_row_exists(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The size policy, over the one number a client gets to declare."""
    with pytest.raises(Invalid) as refused:
        services.create_file(
            tenant=tenant,
            actor=owner_actor,
            filename="enormous.iso",
            content_type="application/octet-stream",
            size_bytes=services.MAX_DECLARED_UPLOAD_BYTES + 1,
            purpose=StoredFile.Purpose.UPLOAD,
        )

    assert "size_bytes" in refused.value.errors
    assert not StoredFile.objects.filter(tenant=tenant).exists()


# --- replacing ----------------------------------------------------------------


def test_replacing_a_document_leaves_the_old_version_exactly_where_it_was(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The whole reason `FileVersion` exists: a replace is additive.

    Version 1's key, digest and size are quoted by audit rows and export
    manifests. After a replace they still mean what they meant.
    """
    first = services.create_file(
        tenant=tenant,
        actor=owner_actor,
        filename="contract.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )
    _measured(first.version, owner_actor, tenant)

    second = services.add_version(
        tenant=tenant,
        actor=owner_actor,
        file=first.file,
        content_type="application/pdf",
        size_bytes=len(BODY),
    )

    assert second.version.version == 2
    assert second.version.key != first.version.key
    unchanged = FileVersion.objects.get(pk=first.version.pk)
    assert unchanged.status == FileVersion.Status.STORED
    assert unchanged.sha256 == DIGEST
    assert unchanged.key == first.version.key


def test_a_document_another_branch_owns_cannot_be_named(
    tenant: Tenant, root_org: Organization, owner: User, owner_actor: Actor
) -> None:
    """Rule 26, and the refusal is `not_found` — not-there and not-yours are one answer.

    Two sibling branches. Somebody standing in one hands over the id of a
    document filed in the other. Tenancy does not catch it (the row IS in the
    tenant) and the policy does not catch it (`can_replace` is about the verb),
    which is exactly the hole `may_be_named` exists for.
    """
    left = create_organization(
        tenant=tenant, parent=root_org, name="Left", slug="left", actor=owner_actor
    )
    right = create_organization(
        tenant=tenant, parent=root_org, name="Right", slug="right", actor=owner_actor
    )
    add_membership(
        user=owner, tenant=tenant, organization=left, role=Membership.Role.ADMIN, actor=owner_actor
    )
    in_the_right_branch = services.create_file(
        tenant=tenant,
        actor=actor_for(user=owner, tenant=tenant, org=right),
        filename="theirs.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )

    with pytest.raises(NotFound):
        services.add_version(
            tenant=tenant,
            actor=actor_for(user=owner, tenant=tenant, org=left),
            file=in_the_right_branch.file,
            content_type="application/pdf",
            size_bytes=len(BODY),
        )


def test_an_upload_url_is_refused_for_a_version_whose_bytes_already_landed(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The service-side fence (ADR files-2, criterion 6), at the one seam that mints.

    Driven at `_upload_url_for` directly and deliberately: both of today's public
    minting sites allocate a fresh `PENDING` version a line earlier, so neither
    can reach this refusal — and a fence nothing can walk into is a fence nobody
    has proved. A re-issue door is the caller that will, and it routes through
    this function rather than through `storage.presign_put`.
    """
    ticket = services.create_file(
        tenant=tenant,
        actor=owner_actor,
        filename="contract.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )
    stored = _measured(ticket.version, owner_actor, tenant)

    with pytest.raises(Conflict):
        services._upload_url_for(tenant=tenant, version=stored)


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_replaces_get_two_ordinals_and_never_one_twice(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """Under real concurrency: `select_for_update` on the document.

    `transaction=True` and real threads, because the thing being proved only
    exists between two connections — a single-threaded test would allocate v2 and
    v3 for reasons that have nothing to do with the lock. A barrier puts both
    threads at the door at the same moment, so the second one is genuinely
    waiting on the first's lock rather than arriving after it.

    Both halves asserted: two DISTINCT ordinals came back, and the table holds
    exactly the rows those ordinals name. The unique constraint on
    `(file, version)` would have turned a lost update into an `IntegrityError`
    rather than a silent duplicate — which is the point of having both — so the
    failure this catches is the one where the lock is absent and one thread's
    write simply loses.
    """
    filed = services.create_file(
        tenant=tenant,
        actor=owner_actor,
        filename="contract.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )
    both_at_the_door = threading.Barrier(2, timeout=30)
    allocated: list[int] = []
    broke: list[BaseException] = []

    def replace() -> None:
        try:
            both_at_the_door.wait()
            allocated.append(
                services.add_version(
                    tenant=tenant,
                    actor=actor_for(user=owner, tenant=tenant, org=filed.file.organization),
                    file=filed.file,
                    content_type="application/pdf",
                    size_bytes=len(BODY),
                ).version.version
            )
        except BaseException as failure:  # noqa: BLE001 - reported, not swallowed
            broke.append(failure)
        finally:
            connection.close()

    racers = [threading.Thread(target=replace) for _ in range(2)]
    for racer in racers:
        racer.start()
    for racer in racers:
        racer.join(timeout=30)

    assert broke == []
    assert sorted(allocated) == [2, 3]
    assert sorted(
        FileVersion.objects.filter(file=filed.file).values_list("version", flat=True)
    ) == [1, 2, 3]


# --- confirming ---------------------------------------------------------------


def test_confirming_starts_one_run_per_version_at_a_derived_id(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """House rule 18, and the reason the id is per VERSION rather than per file.

    Two confirms, one run — and the id is DERIVED here rather than remembered,
    because a test that stored the id it saw could not tell a deterministic id
    from a lucky one.
    """
    ticket = services.create_file(
        tenant=tenant,
        actor=owner_actor,
        filename="contract.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )

    services.confirm_upload(
        tenant=tenant, actor=owner_actor, version=ticket.version, idempotency_key="up-1"
    )
    services.confirm_upload(
        tenant=tenant, actor=owner_actor, version=ticket.version, idempotency_key="up-1"
    )

    expected = workflow_id(tenant=tenant, app="files", noun="version", key=str(ticket.version.pk))
    runs = list(WorkflowRun.objects.for_tenant(tenant).filter(type="FinalizeUpload"))
    assert [run.workflow_id for run in runs] == [expected]


def test_two_versions_of_one_document_confirm_as_two_runs(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """Per-version and not per-file: two uploads in flight are two runs, never one."""
    first = services.create_file(
        tenant=tenant,
        actor=owner_actor,
        filename="contract.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )
    second = services.add_version(
        tenant=tenant,
        actor=owner_actor,
        file=first.file,
        content_type="application/pdf",
        size_bytes=len(BODY),
    )

    services.confirm_upload(
        tenant=tenant, actor=owner_actor, version=first.version, idempotency_key="a"
    )
    services.confirm_upload(
        tenant=tenant, actor=owner_actor, version=second.version, idempotency_key="b"
    )

    assert WorkflowRun.objects.for_tenant(tenant).filter(type="FinalizeUpload").count() == 2


def test_confirming_with_no_key_is_refused(tenant: Tenant, owner_actor: Actor) -> None:
    """A confirm with no key is a caller who has not thought about their own retries."""
    ticket = services.create_file(
        tenant=tenant,
        actor=owner_actor,
        filename="contract.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )

    with pytest.raises(Invalid) as refused:
        services.confirm_upload(
            tenant=tenant, actor=owner_actor, version=ticket.version, idempotency_key="   "
        )

    assert "idempotency_key" in refused.value.errors
    assert not WorkflowRun.objects.for_tenant(tenant).filter(type="FinalizeUpload").exists()


# --- recording what was measured ---------------------------------------------


def test_finalizing_writes_the_measurement_meters_it_and_says_so(
    tenant: Tenant, root_org: Organization, owner_actor: Actor
) -> None:
    """One transaction: the status, the digest, the promotion, the meter, the event.

    The metered quantity is asserted against the MEASURED size and not against
    what the caller declared, which is the property the whole app is shaped
    around — a meter fed a client's own number is a meter a client can set.
    """
    ticket = services.create_file(
        tenant=tenant,
        actor=owner_actor,
        filename="contract.pdf",
        content_type="application/pdf",
        # Declared as something else entirely, so a service that metered the
        # declaration rather than the measurement would fail here.
        size_bytes=7,
        purpose=StoredFile.Purpose.UPLOAD,
    )

    stored = _measured(ticket.version, owner_actor, tenant)

    assert stored.status == FileVersion.Status.STORED
    assert stored.sha256 == DIGEST
    assert stored.size_bytes == len(BODY)
    assert StoredFile.objects.get(pk=ticket.file.pk).current_version == 1

    entries = _entries(tenant)
    assert len(entries) == 1
    assert entries[0].quantity == Decimal(len(BODY))
    assert entries[0].organization_id == root_org.pk
    assert entries[0].ref_id == stored.pk
    assert entries[0].idempotency_key == f"{stored.pk}:{STORAGE_BYTES}"

    events = _stored_events(tenant)
    assert len(events) == 1
    assert events[0].payload["version"]["sha256"] == DIGEST
    assert events[0].payload["version"]["version"] == 1
    assert events[0].payload["current_version"] == 1
    assert events[0].organization_id == root_org.pk


def test_a_retried_finalize_records_exactly_one_usage_entry(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """**THE HEADLINE.** Temporal runs an activity at least once. Bill once.

    This is `apps/usage`'s ratified same-key-replay semantics in their live case:
    the second call derives the same idempotency key from the same version, the
    ledger recognises it, and returns the first row **quietly, inside this
    caller's transaction** — an `IntegrityError` escaping there would have rolled
    back the very finalize it was retrying.

    Everything else is idempotent alongside it: one `STORED` transition, one
    promotion, and **one event**, because a subscriber that received two `stored`
    notifications for one object would have to de-duplicate a fact that only
    happened once.

    The red half is `test_a_meter_key_that_is_not_derived_from_the_row_double_bills`
    below: sever the derivation, and this becomes two entries.
    """
    ticket = services.create_file(
        tenant=tenant,
        actor=owner_actor,
        filename="contract.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )

    once = _measured(ticket.version, owner_actor, tenant)
    twice = _measured(ticket.version, owner_actor, tenant)

    assert once.pk == twice.pk
    assert twice.status == FileVersion.Status.STORED
    assert len(_entries(tenant)) == 1
    assert _entries(tenant)[0].quantity == Decimal(len(BODY))
    assert len(_stored_events(tenant)) == 1
    assert StoredFile.objects.get(pk=ticket.file.pk).current_version == 1


def test_a_meter_key_that_is_not_derived_from_the_row_double_bills(
    tenant: Tenant, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The red half of the test above, planted and reverted by the harness.

    The guard being severed is one expression: the idempotency key derived from
    the version's primary key and the meter name. Replace it with something that
    differs per call — which is what a key invented at the call site does — and
    the ledger has no way to recognise the retry. Two entries, and a customer
    billed twice for one document.

    Kept as a permanent regression rather than run once and deleted, because the
    thing it protects is invisible in a diff: a plausible key spelled a
    plausible way still double-bills.
    """
    ticket = services.create_file(
        tenant=tenant,
        actor=owner_actor,
        filename="contract.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )
    calls = iter(range(100))

    def with_a_fresh_key_each_time(**kwargs: Any) -> Any:
        # The REAL ledger, reached by its own name rather than through the
        # attribute being replaced: everything about the recording stays honest
        # except the one expression under test.
        kwargs["idempotency_key"] = f"finalize-{next(calls)}"
        return record_usage(**kwargs)

    monkeypatch.setattr(services, "record_usage", with_a_fresh_key_each_time)

    _measured(ticket.version, owner_actor, tenant)
    _measured(ticket.version, owner_actor, tenant)

    assert len(_entries(tenant)) == 2
    assert sum(entry.quantity for entry in _entries(tenant)) == Decimal(2 * len(BODY))


def test_a_retry_that_measured_something_else_is_refused_by_the_ledger(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The ledger's OTHER ratified half, live: a key names one unit of work.

    Two calls under one key disagreeing about the quantity is not a retry, it is
    two different claims about what happened — and this table's whole value is
    that it does not guess. The refusal propagates out of `record_stored`'s
    transaction, so the version keeps the digest it was first recorded with
    rather than being left holding one the ledger disagrees with.

    There is deliberately no second opinion in `record_stored` about this. The
    refusal a caller gets is the ledger's own sentence, which is the one that
    knows both numbers.
    """
    ticket = services.create_file(
        tenant=tenant,
        actor=owner_actor,
        filename="contract.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )
    _measured(ticket.version, owner_actor, tenant)

    with pytest.raises(Conflict):
        _measured(
            ticket.version,
            owner_actor,
            tenant,
            sha256=hashlib.sha256(b"different bytes").hexdigest(),
            size_bytes=len(BODY) + 1,
        )

    kept = FileVersion.objects.get(pk=ticket.version.pk)
    assert kept.sha256 == DIGEST
    assert kept.size_bytes == len(BODY)
    assert len(_entries(tenant)) == 1


@pytest.mark.parametrize("order", [(1, 2), (2, 1)])
def test_promotion_is_upward_only_whichever_order_they_finalize_in(
    tenant: Tenant, owner_actor: Actor, order: tuple[int, int]
) -> None:
    """Two versions finalizing out of order converge on the highest STORED one.

    Both orders driven, because "it happened to work" and "it cannot go
    backwards" look identical when only the ordinary order is tested.
    """
    first = services.create_file(
        tenant=tenant,
        actor=owner_actor,
        filename="contract.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose=StoredFile.Purpose.UPLOAD,
    )
    second = services.add_version(
        tenant=tenant,
        actor=owner_actor,
        file=first.file,
        content_type="application/pdf",
        size_bytes=len(BODY),
    )
    by_ordinal = {1: first.version, 2: second.version}

    for ordinal in order:
        _measured(by_ordinal[ordinal], owner_actor, tenant)

    assert StoredFile.objects.get(pk=first.file.pk).current_version == 2
    assert len(_entries(tenant)) == 2


# --- the generation seam ------------------------------------------------------


def test_store_bytes_records_and_meters_what_the_store_MEASURED(
    tenant: Tenant, root_org: Organization, owner_actor: Actor, bucket: str
) -> None:
    """The generation path, against a live MinIO, measured through the same instrument.

    An earlier test proved the archive and the database agree about a digest. This is that
    property extended to the number that costs money: the bytes go up, are
    streamed back down and counted, and the `UsageEntry`'s quantity is that
    count — not `len(content)` as this test happens to know it, though it is
    asserted to be equal to it, which is the whole point.
    """
    version = services.store_bytes(
        tenant=tenant,
        actor=owner_actor,
        filename="export.zip",
        content_type="application/zip",
        content=BODY,
        purpose=StoredFile.Purpose.EXPORT,
    )

    assert version.status == FileVersion.Status.STORED
    assert version.version == 1
    assert version.sha256 == DIGEST
    assert version.size_bytes == len(BODY)
    assert version.organization_id == root_org.pk

    in_the_bucket = storage.sha256_of(tenant=tenant, key=version.key)
    assert in_the_bucket.sha256 == version.sha256
    assert in_the_bucket.size_bytes == version.size_bytes

    entries = _entries(tenant)
    assert len(entries) == 1
    assert entries[0].quantity == Decimal(in_the_bucket.size_bytes)
    assert StoredFile.objects.get(pk=version.file_id).current_version == 1


def test_store_bytes_versions_an_existing_document(
    tenant: Tenant, owner_actor: Actor, bucket: str
) -> None:
    """`file=` is the replace half of the same seam — a new object, never an overwrite."""
    first = services.store_bytes(
        tenant=tenant,
        actor=owner_actor,
        filename="export.zip",
        content_type="application/zip",
        content=BODY,
        purpose=StoredFile.Purpose.EXPORT,
    )
    document = StoredFile.objects.get(pk=first.file_id)

    second = services.store_bytes(
        tenant=tenant,
        actor=owner_actor,
        filename="export.zip",
        content_type="application/zip",
        content=BODY + b"more",
        purpose=StoredFile.Purpose.EXPORT,
        file=document,
    )

    assert second.version == 2
    assert second.key != first.key
    assert second.sha256 == hashlib.sha256(BODY + b"more").hexdigest()
    assert StoredFile.objects.get(pk=document.pk).current_version == 2
    # Version 1's object is still exactly where it was, with its own digest.
    assert storage.sha256_of(tenant=tenant, key=first.key).sha256 == DIGEST


def test_store_bytes_meters_the_branch_the_run_was_acting_for(
    tenant: Tenant, root_org: Organization, owner: User, owner_actor: Actor, bucket: str
) -> None:
    """The hat decides where the bytes are billed, which is why activities restore it.

    An actor wearing the branch's hat — which is what an activity builds out of
    the workflow's headers — meters that branch and not the tenant's root. A run
    that quietly acted for the whole tenant would put a sub-seller's storage on
    everybody's ledger, and `record_usage` refuses a hatless caller outright
    rather than defaulting to the root.
    """
    branch = create_organization(
        tenant=tenant, parent=root_org, name="Branch", slug="branch", actor=owner_actor
    )
    add_membership(
        user=owner,
        tenant=tenant,
        organization=branch,
        role=Membership.Role.ADMIN,
        actor=owner_actor,
    )

    version = services.store_bytes(
        tenant=tenant,
        actor=actor_for(user=owner, tenant=tenant, org=branch),
        filename="branch-export.zip",
        content_type="application/zip",
        content=BODY,
        purpose=StoredFile.Purpose.EXPORT,
    )

    assert version.organization_id == branch.pk
    entries = _entries(tenant)
    assert len(entries) == 1
    assert entries[0].organization_id == branch.pk


def test_the_generation_seam_needs_a_person_and_says_so(
    tenant: Tenant, root_org: Organization
) -> None:
    """A named gap, proved rather than described. **Two callers both meet it.**

    `uploaded_by` is a non-nullable `PROTECT` FK on both models because "who
    filed this" has to stay answerable for as long as the document exists. So
    `store_bytes` needs an actor with a person behind it — which a run started by
    a REQUEST has (the user rides on the workflow's headers) and a run started by
    a SCHEDULE does not.

    Nothing in this cycle generates a document from a schedule, so this is a
    frontier rather than a defect; the refusal below is what makes it a loud one
    instead of an `IntegrityError` at 3am. The day something needs it, the fix is
    a schema decision — a nullable column, with the audit row as the answer to
    who acted — and it is an ADR, not a patch.
    """
    with pytest.raises(Invalid) as refused:
        services.store_bytes(
            tenant=tenant,
            actor=system_actor(tenant, root_org),
            filename="nightly.zip",
            content_type="application/zip",
            content=BODY,
            purpose=StoredFile.Purpose.EXPORT,
        )

    assert "uploaded_by" in refused.value.errors
    assert not StoredFile.objects.filter(tenant=tenant).exists()


# --- the streaming sibling of the generation seam -----------------------------


#: The largest single read this seam may ever ask a body for. The SDK chooses its
#: own chunk — one mebibyte, measured against botocore 1.43 — and what is being
#: asserted is that the body goes over in SOME bounded piece rather than whole.
#: Four times the observed chunk, so an SDK that later reads twice as much at a
#: time is not a false failure, while a seam that read the body WHOLE — which is
#: what `store_bytes(content=body.read())` does — still is, by an order of
#: magnitude.
STREAMED_READ_CEILING = 4 * 1024 * 1024


class _WatchedBody:
    """A spooled body that remembers the largest single `read` anybody asked of it.

    The memory posture, measured deterministically rather than sampled. A seam
    that materialised the body — `put_bytes(content=body.read())` — takes it in
    ONE read, and the largest read is then the whole body; a seam that streams
    takes it in the SDK's own chunks. `tracemalloc` was tried first and rejected:
    its peak is dominated by whatever the process had not yet allocated (a boto3
    client, Django's own machinery), so the same code measured differently
    depending on what ran before it — a flaky test about a property that is not.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.largest_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk: bytes = self._inner.read(size)
        self.largest_read = max(self.largest_read, len(chunk))
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        return int(self._inner.seek(offset, whence))

    def tell(self) -> int:
        return int(self._inner.tell())

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True


def _spooled_body(chunk: bytes, times: int) -> tuple[Any, str, int]:
    """An archive-shaped body: written in pieces, spilled to disk, never held whole.

    The expected digest accumulates as the body is written, so this module never
    holds the bytes it is asserting about either — a test that kept a
    ten-megabyte `bytes` to compare against would be proving the memory posture
    with a counter-example in its own frame.
    """
    spool = SpooledTemporaryFile(max_size=64 * 1024)
    digest = hashlib.sha256()
    for _ in range(times):
        spool.write(chunk)
        digest.update(chunk)
    spool.seek(0)
    return spool, digest.hexdigest(), len(chunk) * times


def test_store_stream_records_and_meters_what_it_measured_on_the_wire(
    tenant: Tenant, root_org: Organization, owner_actor: Actor, bucket: str
) -> None:
    """The service half: the same contract as `store_bytes`, without the read-back.

    `store_bytes` measures by streaming the object back down (`sha256_of`); this
    one measures the pass it sent, because an archive is exactly the body that
    cannot afford a second trip. The property both must have is the one asserted
    here: **the row says what the store holds** — proved by asking the store
    afterwards, which is the same instrument used elsewhere and not the number
    this service returned.
    """
    body, expected, size = _spooled_body(b"export-archive-bytes" * 512, 200)

    version = services.store_stream(
        tenant=tenant,
        actor=owner_actor,
        filename="export.zip",
        content_type="application/zip",
        body=body,
        purpose=StoredFile.Purpose.EXPORT,
    )

    assert version.status == FileVersion.Status.STORED
    assert version.version == 1
    assert version.sha256 == expected
    assert version.size_bytes == size
    assert version.organization_id == root_org.pk

    in_the_bucket = storage.sha256_of(tenant=tenant, key=version.key)
    assert in_the_bucket.sha256 == version.sha256
    assert in_the_bucket.size_bytes == version.size_bytes

    entries = _entries(tenant)
    assert len(entries) == 1
    assert entries[0].quantity == Decimal(size)
    assert StoredFile.objects.get(pk=version.file_id).current_version == 1


def test_store_stream_versions_an_existing_document(
    tenant: Tenant, owner_actor: Actor, bucket: str
) -> None:
    """`file=` is the replace half here too, and version 1 is untouched by it."""
    first_body, first_digest, _ = _spooled_body(b"first-archive", 40)
    first = services.store_stream(
        tenant=tenant,
        actor=owner_actor,
        filename="export.zip",
        content_type="application/zip",
        body=first_body,
        purpose=StoredFile.Purpose.EXPORT,
    )
    document = StoredFile.objects.get(pk=first.file_id)
    second_body, second_digest, _ = _spooled_body(b"second-archive", 40)

    second = services.store_stream(
        tenant=tenant,
        actor=owner_actor,
        filename="export.zip",
        content_type="application/zip",
        body=second_body,
        purpose=StoredFile.Purpose.EXPORT,
        file=document,
    )

    assert second.version == 2
    assert second.key != first.key
    assert second.sha256 == second_digest
    assert StoredFile.objects.get(pk=document.pk).current_version == 2
    assert storage.sha256_of(tenant=tenant, key=first.key).sha256 == first_digest


def test_store_stream_does_not_quietly_become_store_bytes(
    tenant: Tenant, owner_actor: Actor, bucket: str
) -> None:
    """**The posture is the point, so the service is measured and not trusted.**

    A `store_stream` implemented as `store_bytes(content=body.read())` would pass
    every other test in this section and lose the whole reason the streaming path exists. So the
    body counts the largest read it was asked for: that implementation shows one
    read the size of the archive, and this one shows the SDK's own chunks.
    """
    spool, expected, size = _spooled_body(b"export-archive-bytes" * 512, 1200)
    body = _WatchedBody(spool)

    version = services.store_stream(
        tenant=tenant,
        actor=owner_actor,
        filename="export.zip",
        content_type="application/zip",
        body=body,
        purpose=StoredFile.Purpose.EXPORT,
    )

    assert version.sha256 == expected
    assert size > STREAMED_READ_CEILING
    assert 0 < body.largest_read <= STREAMED_READ_CEILING, (
        f"read {body.largest_read} of {size} at once"
    )


def test_store_stream_needs_a_person_exactly_as_store_bytes_does(
    tenant: Tenant, root_org: Organization, bucket: str
) -> None:
    """The same frontier, refused the same way — one seam, not two contracts.

    The same named gap (`uploaded_by` is non-nullable, so a schedule-started run has
    nobody to file the document as) is a property of the models, and a streaming
    sibling that quietly accepted a system actor would have closed it by
    accident, in the one place nobody would think to look.
    """
    body, _, _ = _spooled_body(b"nightly", 10)

    with pytest.raises(Invalid) as refused:
        services.store_stream(
            tenant=tenant,
            actor=system_actor(tenant, root_org),
            filename="nightly.zip",
            content_type="application/zip",
            body=body,
            purpose=StoredFile.Purpose.EXPORT,
        )

    assert "uploaded_by" in refused.value.errors
    assert not StoredFile.objects.filter(tenant=tenant).exists()
