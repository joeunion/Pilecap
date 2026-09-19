"""The world every export test is measured against.

Two tenants, and a tree inside the first one, because both halves of the scoping
question need a way to be wrong: a second tenant is what makes "the archive
exports the deployment" fail, and a sibling branch is what makes "the hat leaks
upward" fail. A world with one tenant and no tree would let both bugs through
while every assertion in this directory passed.

Every row is written by the service that really writes it rather than by
`objects.create`, so the shapes are the shapes production makes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from apps.accounts.models import SsoConnection, User
from apps.accounts.services import create_sso_connection, create_user, verify_sso_domain
from apps.conftest import organ
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, invite_member
from apps.example.services import create_widget, record_widget_entry
from apps.files import storage as files_storage

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator

#: A literal a fixture hands to `create_user`, long enough to clear Django's
#: validators and nothing else. Allow-listed because it is exactly what the
#: scanner is right to look at — a `PASSWORD =` in source — and exactly what a
#: reader should be able to see is fake.
PASSWORD = "a-long-enough-password-for-validators"  # pragma: allowlist secret


@dataclass(frozen=True)
class World:
    """One tenant shaped like a real customer, plus a neighbour to leak into.

    `region` and `branch` are a two-level chain under the root and `sibling` is
    beside `region`, which is the smallest tree in which "downward only" is a
    claim that can fail: an export taken at `region` must contain `branch`'s
    rows, must not contain `sibling`'s, and must not contain the root's.
    """

    tenant: Tenant
    root: Organization
    region: Organization
    branch: Organization
    sibling: Organization
    owner: User
    region_admin: User
    owner_actor: Actor
    region_actor: Actor


@pytest.fixture
def world(tenant: Tenant, owner: User, root_org: Organization) -> World:
    """A tenant with a three-node tree, rows in each node, and two people."""
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
    region_acting = actor_for(user=region_admin, tenant=tenant, org=region)

    # One widget per node, each with a ledger line, so every assertion about
    # which branch's rows travelled has something to be wrong about.
    for org, who in ((root_org, acting), (region, region_acting), (sibling, acting)):
        widget = create_widget(tenant=tenant, actor=who, name=f"Widget at {org.slug}")
        record_widget_entry(tenant=tenant, actor=who, widget=widget, note=f"line at {org.slug}")
    branch_widget = create_widget(
        tenant=tenant,
        actor=actor_for(user=owner, tenant=tenant, org=branch),
        name="Widget at branch",
    )
    record_widget_entry(
        tenant=tenant,
        actor=actor_for(user=owner, tenant=tenant, org=branch),
        widget=branch_widget,
        note="line at branch",
    )
    # A standing offer, which is a tenant-scoped-shaped row that is org-scoped:
    # it is what makes `core.Invitation` travel in a subtree export.
    invite_member(tenant=tenant, email="invited@acme.com", organization=region, actor=acting)
    return World(
        tenant=tenant,
        root=root_org,
        region=region,
        branch=branch,
        sibling=sibling,
        owner=owner,
        region_admin=region_admin,
        owner_actor=acting,
        region_actor=region_acting,
    )


@pytest.fixture
def neighbour(other_tenant: Tenant, stranger: User, other_root_org: Organization) -> Tenant:
    """A second tenant with rows of its own. **The anti-oracle.**

    Every count in an archive can be right while the archive is wrong, and the
    way it is wrong is that somebody else's rows are in it. One foreign row in
    a tenant's export is not a bug to file, it is the export door being worse
    than no export door — so the tests assert ZERO, and this fixture is what
    makes zero a measurement rather than a tautology.
    """
    acting = actor_for(user=stranger, tenant=other_tenant, org=other_root_org)
    widget = create_widget(tenant=other_tenant, actor=acting, name="Globex widget")
    record_widget_entry(tenant=other_tenant, actor=acting, widget=widget, note="globex line")
    invite_member(tenant=other_tenant, email="invited@globex.com", actor=acting)
    return other_tenant


#: The identity provider's own credential, which rule 15 keeps encrypted at rest
#: and which `test_archive_privacy.py` proves does not travel in an archive. A
#: distinctive literal, so a hit anywhere in an export is a hit and never a
#: coincidence — the same discipline the erasure probe uses for its needles.
CLIENT_SECRET = "exports-idp-secret-nobody-should-ever-see"  # pragma: allowlist secret


@pytest.fixture
def sso_connection(world: World) -> SsoConnection:
    """An identity provider for the tenant, with an encrypted credential on it.

    Declared here rather than reused from `apps/accounts/tests/conftest.py`: a
    fixture is only visible under the package that defines it, and a test in
    this app that depended on another app's conftest would be a test that breaks
    the day that app tidies its own fixtures.
    """
    connection = create_sso_connection(
        tenant=world.tenant,
        actor=world.owner_actor,
        name="Acme Okta",
        issuer="https://idp.acme.example",
        client_id="acme-client-id",
        client_secret=CLIENT_SECRET,
        email_domains=["acme.com"],
        default_role=Membership.Role.MEMBER,
    )
    # R2-F1 (a domain claim routes nothing until it is verified): a claim routes nobody until an
    # operator verifies it,
    # and these tests need a connection that behaves like a working one. The
    # same one-line sweep `apps/accounts/tests/conftest.py` makes, repeated here
    # for the reason the docstring above already gives about this fixture.
    verify_sso_domain(
        tenant=world.tenant,
        actor=system_actor(world.tenant),
        connection=connection,
        domain="acme.com",
    )
    return connection


# --- The object store, because the archive now lives in one -------------------
#
# XPr: the archive is filed by `files.services.store_stream` into the files
# seam's bucket, so a test that builds one needs a real bucket the way the files
# app's own tests do. These two are deliberately near-copies of
# `apps/files/tests/conftest.py`'s pair rather than an import of them: a fixture
# is only visible under the package that defines it, and a test in this app that
# reached into another app's conftest would break the day that app tidies its
# own. The duplication is the smaller cost, and it is the same call this file
# already makes about `sso_connection`.
#
# `config/settings/test.py` pins `AWS_STORAGE_BUCKET_NAME = ""` for the ambient
# world, so no export can complete unless a test asks for one of these — which is
# the honest shape: an export door is a door onto object storage, and a
# deployment that has configured none does not have one.


@pytest.fixture
def named_bucket(settings: Any) -> str:
    """A bucket NAME and no bucket. **For a URL, never for bytes.**

    `presign_get` is a local HMAC over a key and a bucket name: it reaches no
    store, and the bucket does not have to exist for the URL to be well-formed
    and correctly signed. So a test whose subject is `download_url` — that it is
    there, that it points at this archive, that the door redirects to it — should
    not pay two MinIO round trips for a bucket it never reads.

    Use `archive_bucket` the moment a test writes, reads back or deletes bytes.
    """
    settings.AWS_STORAGE_BUCKET_NAME = files_storage.derived_bucket_name()
    return files_storage.bucket_name()


@pytest.fixture
@organ("minio")
def archive_bucket(settings: Any) -> Iterator[str]:
    """A real bucket in the compose MinIO, for the length of one test.

    **An organ fixture** (`apps/conftest.py`): every test that reaches this, at
    any depth of its fixture closure, is derived into the `--loop` slow tier and
    runs at push instead of in the rung.

    Emptied in teardown always; destroyed only if this fixture created it —
    `scripts/setup.sh` creates the checkout's own bucket and writes
    it into `.env`, and taking that away would remove `/readyz`'s `storage`
    member from the developer who ran setup.
    """
    settings.AWS_STORAGE_BUCKET_NAME = files_storage.derived_bucket_name()
    name = files_storage.bucket_name()
    client = files_storage.client()
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


def archive_bytes(key: str) -> bytes:
    """Read one archive straight out of the store. **A test's own read.**

    `apps/files/storage.py` deliberately publishes no read-the-bytes function
    (its section "HOW BYTES COME BACK OUT"): production fetches an archive on a
    presigned URL and never through Django. A test is outside that wall by
    construction — `apps/files/tests/test_storage_fence.py::EXCLUDED_DIRECTORY`
    says so — and it is the one caller that legitimately needs the whole object
    in hand, because the claims being made are about what is INSIDE the zip.
    """
    body = files_storage.client().get_object(Bucket=files_storage.bucket_name(), Key=key)["Body"]
    try:
        return bytes(body.read())
    finally:
        body.close()


def archive_exists(key: str) -> bool:
    """Whether there are bytes at this key right now. The purge's own question."""
    client = files_storage.client()
    try:
        client.head_object(Bucket=files_storage.bucket_name(), Key=key)
    except client.exceptions.ClientError:
        return False
    return True
