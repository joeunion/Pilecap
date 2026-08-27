"""The document aggregate: what the database refuses, and where a version lands.

Every assertion here is about a property somebody could otherwise get wrong in a
service — which is why they are made against the DATABASE and the LANDING GATE
rather than against a service that remembers. A constraint runs always; a check
inside a service runs when that service is the one that wrote the row.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.core.actor import actor_for
from apps.core.lifecycle import LifecycleKind
from apps.core.models import Organization, Tenant
from apps.core.services import create_organization
from apps.files import storage
from apps.files.models import FileVersion, StoredFile
from apps.files.tests.conftest import make_version

pytestmark = pytest.mark.django_db


def test_a_document_starts_with_no_current_version(stored_file: StoredFile) -> None:
    """Zero is a state, not a placeholder: nothing is downloadable yet."""
    assert stored_file.current_version == 0
    assert stored_file.archived_at is None


def test_one_row_per_version_of_a_document(stored_file: StoredFile, owner: User) -> None:
    """The ordinal is unique per document — allocation races cannot mint a twin."""
    make_version(file=stored_file, version=1, uploaded_by=owner)
    with pytest.raises(IntegrityError), transaction.atomic():
        FileVersion.objects.create(
            tenant=stored_file.tenant,
            organization=stored_file.organization,
            file=stored_file,
            version=1,
            key="t/x/f/y/v/1-collides-on-the-ordinal",
            content_type="application/pdf",
            uploaded_by=owner,
        )


def test_one_row_per_object_key(stored_file: StoredFile, owner: User) -> None:
    """**A version key is never re-used.** This is the overwrite probe, in the schema.

    Two rows claiming one object is the single thing this design must make
    impossible: it is what a latest-pointer key would have made ordinary, and it
    is what makes a presigned URL's meaning stable after issuance.
    """
    first = make_version(file=stored_file, version=1, uploaded_by=owner)
    with pytest.raises(IntegrityError), transaction.atomic():
        FileVersion.objects.create(
            tenant=stored_file.tenant,
            organization=stored_file.organization,
            file=stored_file,
            version=2,
            key=first.key,
            content_type="application/pdf",
            uploaded_by=owner,
        )


def test_a_stored_version_carries_what_was_measured(stored_file: StoredFile, owner: User) -> None:
    """`stored` without a digest and a size is a row that says nothing was checked."""
    version = make_version(file=stored_file, version=1, uploaded_by=owner)
    version.status = FileVersion.Status.STORED
    with pytest.raises(IntegrityError), transaction.atomic():
        version.save()


def test_a_pending_version_may_have_neither(pending_version: FileVersion) -> None:
    """The implication runs one way: nothing measured is the honest pending state."""
    assert pending_version.status == FileVersion.Status.PENDING
    assert pending_version.size_bytes is None
    assert pending_version.sha256 == ""


def test_a_version_lands_where_its_document_lives(
    tenant: Tenant, root_org: Organization, owner: User
) -> None:
    """`derive_org_from` refuses a version filed under the uploader's own hat.

    The failure this closes is silent: a user acting under branch B adds a version
    to branch A's document, the row lands in B, and A — which owns the document —
    cannot see the version of it that was just uploaded. Nothing afterwards can
    tell you it happened.
    """
    branch = create_organization(
        tenant=tenant,
        parent=root_org,
        name="Branch",
        slug="branch",
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
    )
    file = StoredFile.objects.create(
        tenant=tenant,
        organization=root_org,
        filename="contract.pdf",
        purpose=StoredFile.Purpose.UPLOAD,
        uploaded_by=owner,
    )
    with pytest.raises(ValidationError) as refusal:
        make_version(file=file, version=1, uploaded_by=owner, organization=branch)
    assert "organization" in refusal.value.message_dict


def test_a_version_in_its_documents_organization_is_accepted(
    stored_file: StoredFile, owner: User
) -> None:
    """The other half: the gate lets the right organization through."""
    version = make_version(file=stored_file, version=1, uploaded_by=owner)
    assert version.organization_id == stored_file.organization_id


def test_another_tenants_documents_are_absent(
    stored_file: StoredFile, other_tenant: Tenant
) -> None:
    """The sibling test that keeps the scoping assertion from passing vacuously."""
    assert list(StoredFile.objects.for_tenant(stored_file.tenant)) == [stored_file]
    assert list(StoredFile.objects.for_tenant(other_tenant)) == []


def test_both_models_declare_how_their_rows_die() -> None:
    """House rule 31, and the kinds are the honest ones rather than the tidy ones.

    `StoredFile` is UNBOUNDED because archive is soft and purge is not built; a
    `purged` declaration would name a sweeper that does not exist, which is the
    poller-that-was-never-built the vocabulary exists to catch.

    **`FileVersion` said BOUNDED and now says PURGED**, and the change is
    the declaration catching up with the code rather than the code changing its
    mind. The CASCADE asserted below is still there and still true of every
    version that reaches `STORED`; what was added is a sweeper for the ones that
    never do, and `_refuse_malformed` names that shape exactly — a sweeper on a
    bounded table is either a wrong kind or a delete nobody meant to declare. The
    chain from the declaration to its schedule, and what the sweep takes and
    leaves, are `tests/test_lifecycle.py`'s subject; this stays the model's own
    two-line statement about its two fields.
    """
    assert StoredFile.lifecycle.kind is LifecycleKind.UNBOUNDED
    assert "archive is soft" in StoredFile.lifecycle.reason
    assert FileVersion.lifecycle.kind is LifecycleKind.PURGED
    assert FileVersion.lifecycle.purged_by == "apps.files.services.purge_pending_versions"
    assert FileVersion._meta.get_field("file").remote_field.on_delete is not None


def test_both_tables_keep_the_tenant_leading_recency_index() -> None:
    """ADR core-11's composite survives, because neither Meta declares `indexes`.

    Django does not merge `Meta.indexes` down an inheritance chain: a concrete
    model that declares its own SHADOWS the abstract one, silently, and the list
    read of a big table goes from an index scan to a sequential one. House rule 37
    is the tripwire; this is the same claim asserted from inside the app that
    would break it.
    """
    for model in (StoredFile, FileVersion):
        names = {index.name for index in model._meta.indexes}
        assert f"{model.__name__.lower()}_recency" in names, names


def test_a_key_never_carries_a_renamable_name(stored_file: StoredFile, owner: User) -> None:
    """The identity that survives a rename is the key, and the key survives it."""
    version = make_version(file=stored_file, version=1, uploaded_by=owner)
    before = version.key
    stored_file.filename = "invoice-final-FINAL.pdf"
    stored_file.save(update_fields=["filename"])
    version.refresh_from_db()
    assert version.key == before
    assert "invoice" not in version.key
    assert (
        storage.version_key(tenant=stored_file.tenant, file_pk=stored_file.pk, version=1) == before
    )
