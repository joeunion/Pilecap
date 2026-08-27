"""`manage.py storage_audit` — the tripwire for the thing no check can see.

House rule 48 fences the object store to one module; rule 48's own
`does_not_cover` says the bucket's own state and policy are the blind spot it is
one half of, and names this command as the partial answer. So the properties
below are what "partial answer" is allowed to mean:

* **it refuses to judge what it cannot read** — exit 2, never 0, for no bucket,
  a store that will not answer, and a policy it may not see. The instrument
  checklist's line and `manage.py integrations`' convention;
* **it sees the retention posture ON THE BUCKET** (the live half). The paper
  half is `apps/core/tests/test_archive_retention.py`, which reads
  `deploy/provision.sh` as text: it proves two declared numbers agree and cannot
  see a bucket at all. Both directions are driven here against a real store —
  versioning on with no rule is DRIFT, and the same bucket with the rule applied
  agrees;
* **it sees the three ways a bucket and its rows come apart** — missing, orphan,
  drifted — and does not cry wolf on the fourth thing that looks like all three,
  an upload in flight.

**Most of this reaches the compose MinIO** and is therefore in the slow tier by
derivation (`apps/conftest.py`'s `organ`). That is the honest cost: a command
whose whole subject is what a bucket says cannot be proved against a bucket that
is not there. The two exit-2 refusals that need no store are fast on purpose,
because they are the ones a fresh clone hits first.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import pytest
from django.core.management import call_command

from apps.conftest import organ
from apps.core.actor import actor_for
from apps.files import storage
from apps.files.models import FileVersion, StoredFile
from apps.files.services import record_stored

from .conftest import make_version

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator

    from apps.accounts.models import User
    from apps.core.models import Organization, Tenant

pytestmark = pytest.mark.django_db

#: A port nothing listens on — see `test_integrations.py` for why 9.
NOWHERE = "http://127.0.0.1:9"

#: What `deploy/provision.sh` writes onto the media bucket, in the shape boto3
#: takes it. **The abort-incomplete-uploads rule that rides beside it there is
#: deliberately absent**: this MinIO refuses `AbortIncompleteMultipartUpload`
#: outright (`InvalidArgument`, measured against the compose image),
#: so a laptop cannot drive that clause. The reader for it exists and is
#: DECLARED UNPROVEN rather than assumed, exactly as `create_bucket_if_absent`'s
#: region clause is.
NONCURRENT_EXPIRY_RULE = {
    "Rules": [
        {
            "ID": "expire-noncurrent-versions",
            "Status": "Enabled",
            "Filter": {"Prefix": ""},
            "NoncurrentVersionExpiration": {"NoncurrentDays": 7},
        }
    ]
}

BODY = b"a document somebody filed\n" * 64
DIGEST = hashlib.sha256(BODY).hexdigest()


# --- the two refusals that need no store --------------------------------------


def test_a_deployment_with_no_bucket_is_exit_2_and_never_a_clean_report(
    settings: Any, capsys: Any
) -> None:
    """**The instrument checklist's line.** No bucket is not "storage agrees".

    A 0 here would be the worst possible answer: an operator asking "is my object
    storage consistent" on a deployment that has none would be told yes.
    """
    settings.AWS_STORAGE_BUCKET_NAME = ""
    capsys.readouterr()

    with pytest.raises(SystemExit) as leaving:
        call_command("storage_audit")

    assert leaving.value.code == 2
    assert storage.BUCKET_SETTING in capsys.readouterr().err


def test_a_store_that_will_not_answer_is_exit_2_with_the_remedy(settings: Any, capsys: Any) -> None:
    """ "I could not look" and "I looked and it is fine" are different answers."""
    settings.AWS_STORAGE_BUCKET_NAME = "a-bucket-nothing-is-listening-for"
    settings.AWS_S3_ENDPOINT_URL = NOWHERE
    capsys.readouterr()

    with pytest.raises(SystemExit) as leaving:
        call_command("storage_audit")

    err = capsys.readouterr().err
    assert leaving.value.code == 2
    assert "did not answer" in err
    assert storage.UNREACHABLE_BUCKET_REMEDY in err


def test_an_unknown_tenant_slug_is_exit_2_and_not_a_clean_empty_report(
    settings: Any, capsys: Any
) -> None:
    """A narrowed audit whose narrowing matched nothing looks exactly like a pass.

    Resolved before anything is read, so a typo costs one query and a sentence
    rather than a green report over an empty set.
    """
    settings.AWS_STORAGE_BUCKET_NAME = ""
    capsys.readouterr()

    with pytest.raises(SystemExit) as leaving:
        call_command("storage_audit", tenant="no-such-tenant")

    assert leaving.value.code == 2
    assert "no tenant has the slug" in capsys.readouterr().err


def test_a_policy_it_may_not_read_is_exit_2_and_says_why(
    bucket: str, monkeypatch: Any, capsys: Any
) -> None:
    """The third way it can fail to look, and the one worth a sentence of its own.

    A bucket can answer a `HEAD` and still refuse `GetBucketLifecycleConfiguration`
    — a role with `s3:ListBucket` and no `s3:GetLifecycleConfiguration` is an
    ordinary shape. Skipping the section and printing a green verdict would be
    this whole file's failure mode, so the refusal is fatal and the report says
    what was not read.

    Driven by making the seam refuse rather than by re-authorising MinIO: the
    thing under test is the COMMAND'S handling of a refusal, and
    `test_the_seam_refuses_to_guess_a_posture_it_cannot_read` below proves the
    seam really raises against a store that will not answer.
    """

    def refuse() -> storage.RetentionPosture:
        raise storage.StorageUnreadable("this role may not read the lifecycle configuration")

    monkeypatch.setattr(storage, "retention_posture", refuse)
    capsys.readouterr()

    with pytest.raises(SystemExit) as leaving:
        call_command("storage_audit")

    err = capsys.readouterr().err
    assert leaving.value.code == 2
    assert "may not read the lifecycle configuration" in err
    assert "not a report that it is fine" in err


def test_the_seam_refuses_to_guess_a_posture_it_cannot_read(settings: Any) -> None:
    """The other half of the pair above, against a store that is really not there."""
    settings.AWS_STORAGE_BUCKET_NAME = "a-bucket-nothing-is-listening-for"
    settings.AWS_S3_ENDPOINT_URL = NOWHERE

    with pytest.raises(storage.StorageUnreadable):
        storage.retention_posture()


# --- The live half: the retention posture, on a real bucket ---------------------


@pytest.fixture
@organ("minio")
def retention_bucket(settings: Any) -> Iterator[str]:
    """A bucket of this test's own, so versioning can be turned ON and cleaned up.

    **Not the shared `bucket` fixture**, and the reason is a leak rather than a
    preference: S3 versioning cannot be turned off once it has been on — only
    suspended — and that fixture deliberately does not destroy a bucket it did
    not create, because on a laptop that bucket belongs to the checkout
    (`scripts/setup.sh` made it). A test that enabled versioning on it would
    leave a permanent change behind in somebody's development environment.

    So this one makes its own, always owns it, and always takes it away —
    including every noncurrent version and delete marker, which an ordinary
    empty-the-bucket teardown does not reach and which S3 refuses to delete a
    bucket over.

    **The SETTING holds the unsuffixed name and `bucket_name()` adds the
    worker's, exactly as `.env` and `bucket_name()` do in a deployment.** Written
    the other way round first — derive, suffix, then configure the suffixed name
    — it read perfectly serially and produced `…-gw1-rtn-gw1` under xdist,
    because `_worker_suffixed` ran over a name that already carried a suffix.
    The gate found it on the first parallel run; the pattern is worth restating
    wherever a test names a bucket.
    """
    settings.AWS_STORAGE_BUCKET_NAME = f"{storage.derived_bucket_name()}-rtn"
    name = storage.bucket_name()
    s3 = storage.client()
    s3.create_bucket(Bucket=name)
    try:
        yield name
    finally:
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=name):
            victims = [
                {"Key": row["Key"], "VersionId": row["VersionId"]}
                for kind in ("Versions", "DeleteMarkers")
                for row in page.get(kind, [])
            ]
            if victims:
                s3.delete_objects(Bucket=name, Delete={"Objects": victims})
        s3.delete_bucket(Bucket=name)


@pytest.fixture
def versioned(retention_bucket: str) -> str:
    """That bucket, with versioning on. The deployment already points at it."""
    storage.client().put_bucket_versioning(
        Bucket=retention_bucket, VersioningConfiguration={"Status": "Enabled"}
    )
    return retention_bucket


def test_an_unversioned_bucket_owes_no_lifecycle_rule_and_says_why(
    retention_bucket: str, capsys: Any
) -> None:
    """The baseline, stated rather than left as the absence of a warning.

    On an unversioned bucket a delete is a delete, `purge_exports`' `delete_object`
    really removes the bytes, and house rule 31's `purged` is true with no
    lifecycle rule anywhere. A report that stayed silent here would leave a reader
    unable to tell "no rule and none needed" from "no rule and nobody looked".
    """
    capsys.readouterr()

    call_command("storage_audit")

    out = capsys.readouterr().out
    assert "versioning      off" in out
    assert "a delete is a delete" in out
    assert "DRIFT" not in out


def test_versioning_on_with_no_expiry_rule_is_drift_on_the_real_bucket(
    versioned: str, capsys: Any
) -> None:
    """**Live.** The hole the paper half structurally cannot see.

    Turn versioning on and `delete_object` writes a delete marker and keeps the
    object forever. Every instrument on this tree goes on reporting the archive
    purged — `Export` is gone, `/readyz` is green — and a copy of a tenant's whole
    database is still in the bucket. Nothing in `quality/` can see this, and
    nothing did until this line.
    """
    capsys.readouterr()

    with pytest.raises(SystemExit) as leaving:
        call_command("storage_audit")

    out = capsys.readouterr().out
    assert leaving.value.code == 1
    assert "versioning      on" in out
    assert "DRIFT" in out
    assert "no enabled rule expires a noncurrent version" in out
    # The remedy names where the posture is SET, which is the only place it can
    # be set (`deploy/provision.sh`) — a bucket lifecycle is deployment state.
    assert "provision.sh" in out


def test_the_same_bucket_agrees_once_the_rule_provision_sets_is_applied(
    versioned: str, capsys: Any
) -> None:
    """The other direction, on the same bucket, one API call apart.

    The pair is what makes the assertion above a measurement rather than a
    property of MinIO's defaults: the only thing that changed between the two is
    the lifecycle configuration `deploy/provision.sh` writes.
    """
    storage.client().put_bucket_lifecycle_configuration(
        Bucket=versioned, LifecycleConfiguration=NONCURRENT_EXPIRY_RULE
    )
    capsys.readouterr()

    call_command("storage_audit")

    out = capsys.readouterr().out
    assert "DRIFT" not in out
    assert "noncurrent versions expire after 7 day(s)" in out
    assert "expire-noncurrent-versions" in out


def test_a_disabled_rule_is_not_a_posture(versioned: str, capsys: Any) -> None:
    """A rule somebody wrote and turned off must not read as protection.

    The cheapest possible way for this instrument to lie: count the rules rather
    than the enabled ones, and a `Status: Disabled` line in a console reads as a
    bucket that lets go of its noncurrent versions when it does not.
    """
    disabled = {
        "Rules": [
            {
                **NONCURRENT_EXPIRY_RULE["Rules"][0],
                "Status": "Disabled",
            }
        ]
    }
    storage.client().put_bucket_lifecycle_configuration(
        Bucket=versioned, LifecycleConfiguration=disabled
    )
    capsys.readouterr()

    with pytest.raises(SystemExit) as leaving:
        call_command("storage_audit")

    assert leaving.value.code == 1
    assert "DRIFT" in capsys.readouterr().out


# --- the objects against the rows ---------------------------------------------


@pytest.fixture
def a_stored_version(
    bucket: str, tenant: Tenant, root_org: Organization, owner: User, stored_file: StoredFile
) -> FileVersion:
    """One document whose bytes really are in the store, recorded the real way."""
    version = make_version(file=stored_file, version=1, uploaded_by=owner)
    storage.put_bytes(tenant=tenant, key=version.key, content=BODY, content_type="application/pdf")
    return record_stored(
        tenant=tenant,
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
        version=version,
        sha256=DIGEST,
        size_bytes=len(BODY),
    )


def test_a_bucket_that_matches_its_rows_agrees(a_stored_version: FileVersion, capsys: Any) -> None:
    capsys.readouterr()

    call_command("storage_audit")

    out = capsys.readouterr().out
    assert "1 stored" in out
    assert "The bucket agrees with every row" in out


def test_a_stored_row_whose_object_is_gone_is_reported_missing(
    a_stored_version: FileVersion, tenant: Tenant, capsys: Any
) -> None:
    """The row quotes a digest that checks against nothing and a download 404s."""
    storage.delete_object(tenant=tenant, key=a_stored_version.key)
    capsys.readouterr()

    with pytest.raises(SystemExit) as leaving:
        call_command("storage_audit")

    out = capsys.readouterr().out
    assert leaving.value.code == 1
    assert "missing" in out
    assert a_stored_version.key in out


def test_an_object_no_row_claims_is_reported_orphan(
    a_stored_version: FileVersion, tenant: Tenant, capsys: Any
) -> None:
    """Bytes nobody can reach, nobody will purge, and somebody is paying for.

    The key is a well-formed one for a version that was never allocated — which
    is what an interrupted sweep, a restored backup or a hand-run script leaves
    behind, and exactly what a scoped read through the ORM can never surface.
    """
    orphan = storage.version_key(tenant=tenant, file_pk=a_stored_version.file_id, version=99)
    storage.put_bytes(tenant=tenant, key=orphan, content=b"nobody's", content_type="text/plain")
    capsys.readouterr()

    with pytest.raises(SystemExit) as leaving:
        call_command("storage_audit")

    out = capsys.readouterr().out
    assert leaving.value.code == 1
    assert "orphan" in out
    assert orphan in out


def test_an_object_that_changed_under_a_stored_row_is_reported(
    a_stored_version: FileVersion, tenant: Tenant, capsys: Any
) -> None:
    """The bytes are not the bytes this platform witnessed. Caught on size alone.

    Simulated the way it would really happen — out of band, through a door the
    wall now forbids — rather than by recording a number we knew was wrong: the
    object is deleted and rewritten, which is what a console upload or a restored
    backup does, and the row is untouched throughout.
    """
    storage.delete_object(tenant=tenant, key=a_stored_version.key)
    storage.put_bytes(
        tenant=tenant,
        key=a_stored_version.key,
        content=b"different bytes entirely",
        content_type="application/pdf",
    )
    capsys.readouterr()

    with pytest.raises(SystemExit) as leaving:
        call_command("storage_audit")

    out = capsys.readouterr().out
    assert leaving.value.code == 1
    assert "size drift" in out


def test_a_changed_object_of_the_same_length_needs_the_digest_pass(
    a_stored_version: FileVersion, tenant: Tenant, capsys: Any
) -> None:
    """**Why `--digest` exists at all**, proved rather than asserted in a docstring.

    Same length, different bytes: the cheap pass cannot see it, and the expensive
    one can. A report that only ever compared sizes would call this bucket clean
    while every digest in it was a lie.
    """
    same_length = bytes(len(BODY))
    storage.delete_object(tenant=tenant, key=a_stored_version.key)
    storage.put_bytes(
        tenant=tenant,
        key=a_stored_version.key,
        content=same_length,
        content_type="application/pdf",
    )

    capsys.readouterr()
    call_command("storage_audit")
    assert "The bucket agrees with every row" in capsys.readouterr().out

    capsys.readouterr()
    with pytest.raises(SystemExit) as leaving:
        call_command("storage_audit", digest=True)

    out = capsys.readouterr().out
    assert leaving.value.code == 1
    assert "digest" in out


def test_an_upload_in_flight_is_never_reported_as_drift(
    bucket: str, tenant: Tenant, owner: User, stored_file: StoredFile, capsys: Any
) -> None:
    """The fourth thing that looks like all three, and it is none of them.

    A `PENDING` key with an object at it is an upload waiting for finalize; a
    `PENDING` key with nothing at it is a ticket nobody used. Reporting either as
    an orphan or as missing would make this command cry wolf on every busy
    deployment, and a report nobody believes is a report nobody reads.
    """
    landed = make_version(file=stored_file, version=1, uploaded_by=owner)
    make_version(file=stored_file, version=2, uploaded_by=owner)
    storage.put_bytes(tenant=tenant, key=landed.key, content=BODY, content_type="application/pdf")
    capsys.readouterr()

    call_command("storage_audit")

    out = capsys.readouterr().out
    assert "The bucket agrees with every row" in out
    assert "2 allocated key(s), 1 with an object" in out
    assert "orphan" not in out
    assert "missing" not in out


def test_narrowing_to_one_tenant_narrows_both_halves_together(
    a_stored_version: FileVersion, tenant: Tenant, other_tenant: Tenant, capsys: Any
) -> None:
    """`--tenant` moves the prefix and the row filter as one.

    The failure this rules out is the one a half-applied narrowing produces: the
    walk scoped to one tenant's prefix and the rows left deployment-wide would
    report every OTHER tenant's stored version as missing, in a report an
    operator asked to be reassuring.
    """
    capsys.readouterr()

    call_command("storage_audit", tenant=other_tenant.slug)

    out = capsys.readouterr().out
    assert storage.tenant_prefix(other_tenant) in out
    assert "0 stored" in out
    assert "The bucket agrees with every row" in out
    assert a_stored_version.key not in out
