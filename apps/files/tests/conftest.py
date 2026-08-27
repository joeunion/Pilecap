"""The world a files test is measured against, and a real bucket to measure it in.

Three kinds of fixture here and they answer different questions.

The ROW fixtures build documents the way the services do: `StoredFile` at the
acting hat (ADR core-20's placement law), `FileVersion` deriving its organization
from the file it hangs off. Some have no services yet, so they are built with the
manager and `full_clean()` — which is exactly the pair the house service style
uses (`with as_invalid(): row.full_clean()`), so the landing gate really runs.

The BUCKET fixture is a real one, in the compose MinIO, named for this checkout
and this xdist worker. It is created and **destroyed** around each test that asks
for it: a bucket left behind in a shared MinIO is a leak that outlives the rung,
and one shared between two worktrees is the collision `derived_bucket_name`
exists to prevent.

The WORLD fixture is a tenant shaped like a customer — a tree, two people
with different hats, and a neighbouring tenant to leak into. The door tests need
it because "another tenant's documents are absent" and "a sibling branch's
documents are absent" are two different claims, and only the second one is about
the hierarchy: a world with one tenant and no tree would let a whole class of
scoping bug through while every assertion in this directory passed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.conftest import organ
from apps.core.actor import Actor, actor_for
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization
from apps.files import storage
from apps.files.models import FileVersion, StoredFile

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator
    from typing import Any

#: A literal a fixture hands to `create_user`, long enough to clear Django's
#: validators and nothing else. Allow-listed because it is exactly what the
#: scanner is right to look at — a `PASSWORD =` in source — and exactly what a
#: reader should be able to see is fake.
PASSWORD = "a-long-enough-password-for-validators"  # pragma: allowlist secret


@pytest.fixture
def stored_file(tenant: Tenant, root_org: Organization, owner: User) -> StoredFile:
    """A document at the tenant's root, with no version yet.

    `current_version` is 0 and that is the real starting state — see the model:
    a document whose only version is still pending has no current bytes.
    """
    file = StoredFile(
        tenant=tenant,
        organization=root_org,
        filename="invoice.pdf",
        purpose=StoredFile.Purpose.UPLOAD,
        uploaded_by=owner,
    )
    file.full_clean()
    file.save()
    return file


@pytest.fixture
def pending_version(stored_file: StoredFile, owner: User) -> FileVersion:
    """Version 1 of that document, allocated and awaiting its bytes."""
    return make_version(file=stored_file, version=1, uploaded_by=owner)


def make_version(
    *,
    file: StoredFile,
    version: int,
    uploaded_by: User,
    organization: Organization | None = None,
    content_type: str = "application/pdf",
) -> FileVersion:
    """A version row built the way a service will build one.

    `organization` is left to the caller so that a test can hand it a WRONG one
    and watch `derive_org_from` refuse; the default is the file's own, which is
    what the landing gate expects.
    """
    row = FileVersion(
        tenant=file.tenant,
        organization=organization if organization is not None else file.organization,
        file=file,
        version=version,
        key=storage.version_key(tenant=file.tenant, file_pk=file.pk, version=version),
        content_type=content_type,
        uploaded_by=uploaded_by,
    )
    row.full_clean()
    row.save()
    return row


@pytest.fixture
def named_bucket(settings: Any) -> str:
    """A bucket NAME and no bucket. For tests whose subject is a signature.

    `presign_put` and `presign_get` are local HMAC computations: they reach no
    store, and the bucket they name does not have to exist for a URL over it to
    be well-formed and correctly signed. So a test asking "does the URL this
    service mints carry the belt" should not pay two MinIO round trips to create
    and destroy a bucket it never writes to.

    Use `bucket` — the real one — the moment a test PUTs, HEADs, digests or
    deletes. The difference between the two fixtures is the difference between
    proving what we signed and proving what the store did with it, and a test
    that blurs them tends to prove neither.
    """
    settings.AWS_STORAGE_BUCKET_NAME = storage.derived_bucket_name()
    return storage.bucket_name()


@pytest.fixture
@organ("minio")
def bucket(settings: Any) -> Iterator[str]:
    """A real bucket in the compose MinIO, for the length of one test.

    **An organ fixture** (`apps/conftest.py`): every test that reaches this, at
    any depth of its fixture closure, is derived into the `--loop` slow tier and
    runs at push instead of in the rung. Nothing lists those tests; the
    declaration is this decorator and the population follows from it.

    **Named, not derived, at the point of use**: `settings.AWS_STORAGE_BUCKET_NAME`
    is what a deployment configures and what `/readyz` reads, so a test that wants
    object storage configures it the way a deployment does. What it configures it
    TO is this checkout's derived name, which is the answer
    `derived_bucket_name()` exists to give.

    **Emptied in teardown, and destroyed only if this fixture made it.** Objects
    always go: S3 refuses to delete a bucket that still holds anything, and a test
    that left its bytes behind would be the next test's mystery. The BUCKET only
    goes if it was absent when the test started — `scripts/setup.sh`
    creates this checkout's bucket and writes it into `.env`, so on a laptop the
    derived bucket usually already exists and belongs to the checkout rather than
    to the test. Destroying it would take `/readyz`'s `storage` member away from
    the developer who ran setup; creating it unconditionally, which is what this
    fixture used to do, fails outright with `BucketAlreadyOwnedByYou` (found by
    running the suite serially after the new setup step — under xdist the name
    carries a `-gwN` suffix nothing else creates, so the gate would never have
    seen it).
    """
    settings.AWS_STORAGE_BUCKET_NAME = storage.derived_bucket_name()
    name = storage.bucket_name()
    client = storage.client()
    try:
        client.head_bucket(Bucket=name)
        ours = False
    except client.exceptions.ClientError:
        client.create_bucket(Bucket=name)
        ours = True
    try:
        yield name
    finally:
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=name):
            keys = [{"Key": entry["Key"]} for entry in page.get("Contents", [])]
            if keys:
                client.delete_objects(Bucket=name, Delete={"Objects": keys})
        if ours:
            client.delete_bucket(Bucket=name)


# --- The world the door tests are measured against ------------------------------


@dataclass(frozen=True)
class World:
    """One tenant shaped like a real customer, with the hats a scoping claim needs.

    `region` and `branch` are a two-level chain under the root and `sibling` sits
    beside `region`, which is the smallest tree in which "downward only" is a claim
    that can FAIL: a document filed at `region` must be visible to the region's
    admin and to the owner at the root, must be visible from `branch`'s parent and
    not from `sibling`, and a document at the root must not be visible from
    `region`.

    `region_admin` is an ADMIN rather than a member because archiving takes a role
    — a world whose only privileged person sat at the root could not tell "an
    administrator of this branch may archive" from "an owner may archive
    anything".
    """

    tenant: Tenant
    root: Organization
    region: Organization
    branch: Organization
    sibling: Organization
    owner: User
    region_admin: User
    plain_member: User
    owner_actor: Actor
    region_actor: Actor
    member_actor: Actor


@pytest.fixture
def world(tenant: Tenant, owner: User, root_org: Organization) -> World:
    """A tenant with a three-node tree and three people wearing three hats."""
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    region = create_organization(
        tenant=tenant, parent=root_org, name="Region", slug="region", actor=acting
    )
    branch = create_organization(
        tenant=tenant, parent=region, name="Branch", slug="branch", actor=acting
    )
    sibling = create_organization(
        tenant=tenant, parent=root_org, name="Sibling", slug="sibling", actor=acting
    )

    region_admin = create_user(email="region-admin@acme.com", password=PASSWORD)
    add_membership(
        user=region_admin,
        tenant=tenant,
        organization=region,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=acting,
    )
    plain_member = create_user(email="member@acme.com", password=PASSWORD)
    add_membership(
        user=plain_member,
        tenant=tenant,
        organization=region,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=acting,
    )
    return World(
        tenant=tenant,
        root=root_org,
        region=region,
        branch=branch,
        sibling=sibling,
        owner=owner,
        region_admin=region_admin,
        plain_member=plain_member,
        owner_actor=acting,
        region_actor=actor_for(user=region_admin, tenant=tenant, org=region),
        member_actor=actor_for(user=plain_member, tenant=tenant, org=region),
    )


@pytest.fixture
def neighbour(other_tenant: Tenant, stranger: User, other_root_org: Organization) -> Actor:
    """A second tenant with somebody in it. **The anti-oracle.**

    Every count in a scoped list can be right while the list is wrong, and the way
    it is wrong is that somebody else's rows are in it. One foreign document in a
    tenant's list is not a bug to file — it is the door being worse than no door —
    so the tests assert ZERO, and this fixture is what makes zero a measurement
    rather than a tautology.
    """
    return actor_for(user=stranger, tenant=other_tenant, org=other_root_org)
