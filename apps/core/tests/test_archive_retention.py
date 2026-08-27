"""The platform's purge and the bucket's own expiry cannot disagree.

`apps/exports` declares under house rule 31 that an archive is `purged` after
thirty days, and `purge_exports` honours that: it deletes the object and the
row. **On a versioned bucket that deletes nothing.** S3 writes a delete marker
and keeps a noncurrent version indefinitely, so before `deploy/provision.sh`
grew a lifecycle configuration the tree's own instruments all reported an
archive purged while a copy of a tenant's whole database was still in the
bucket — the poller-that-was-never-built shape, one layer below the ORM, where
no rule in `quality/` can see it.

The posture lives in `deploy/provision.sh` because a bucket lifecycle
configuration is deployment state and nothing under `apps/` can carry it (flagged
as not-met rather than ticked off). Which leaves exactly one failure
mode: **two numbers in two files nobody diffs against each other.** This is
that diff.

**Read as TEXT, deliberately, and not imported.** `apps/core` imports nothing
above it (`CoreConfig.depends_on` is empty and `import-linter` holds it), so a
test here that imported `apps.exports` would break the layer contract to check a
pairing. Both numbers are declarations — a shell assignment and a module
constant — and reading a declaration is what a census does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

ROOT = Path(settings.BASE_DIR)
PROVISION = ROOT / "deploy" / "provision.sh"
EXPORTS_MODELS = ROOT / "apps" / "exports" / "models.py"


def _shell_number(name: str) -> int:
    """One `NAME=<int>` assignment out of `provision.sh`. Refuses to guess."""
    text = PROVISION.read_text()
    found = re.findall(rf"^{re.escape(name)}=(\d+)$", text, flags=re.MULTILINE)
    assert len(found) == 1, (
        f"{name} is assigned {len(found)} time(s) in deploy/provision.sh; the "
        "pairing needs exactly one declaration to read."
    )
    return int(found[0])


def _declared_export_retention_days() -> int:
    text = EXPORTS_MODELS.read_text()
    found = re.findall(r"^EXPORT_RETENTION_DAYS = (\d+)$", text, flags=re.MULTILINE)
    assert len(found) == 1, (
        "apps/exports/models.py does not declare EXPORT_RETENTION_DAYS exactly "
        "once. That constant is the authority for how long an archive lives; if "
        "it moved, this pairing has to move with it."
    )
    return int(found[0])


def test_provision_restates_the_platforms_own_retention_window() -> None:
    """The restatement is a COPY, and a copy that drifts is the whole defect.

    `provision.sh` cannot import Django, so it carries the number rather than
    reading it. What makes that safe is this test: change the declaration in
    `apps/exports` and forget the deployment, and the failure is here, in a
    sentence naming both files, rather than in a bucket six months later.
    """
    assert _shell_number("DJB_EXPORT_RETENTION_DAYS") == _declared_export_retention_days(), (
        "deploy/provision.sh's DJB_EXPORT_RETENTION_DAYS no longer matches "
        "apps/exports/models.py's EXPORT_RETENTION_DAYS. The platform's purge and "
        "the bucket's expiry are now describing different windows, and the bucket "
        "is the one nobody will look at."
    )


def test_the_bucket_lets_go_after_the_platform_does_and_never_before() -> None:
    """The direction of the grace window, which is the half that is easy to invert.

    A bucket that expired FIRST would 404 a download while `Export.expires_at`
    still said the archive was live — the disagreement turned around rather than
    closed, and the more visible of the two failures, which is why it is worth an
    assertion of its own rather than a comment.
    """
    assert _shell_number("DJB_ARCHIVE_GRACE_DAYS") > 0, (
        "a grace of zero puts the bucket's expiry level with the platform's purge, "
        "and a race between them decides whether a customer's last download works."
    )


def test_the_only_number_anybody_should_be_quoted_is_derived() -> None:
    """`DJB_ARCHIVE_TOTAL_EXPOSURE_DAYS` is the claim a contract can carry.

    Derived in the shell (`$((a + b))`) rather than typed, so it cannot be
    quoted wrong — and asserted here so the derivation cannot quietly become a
    literal, which is exactly how a number stops tracking the thing it describes.
    """
    text = PROVISION.read_text()
    assert (
        "DJB_ARCHIVE_TOTAL_EXPOSURE_DAYS=$((DJB_EXPORT_RETENTION_DAYS + DJB_ARCHIVE_GRACE_DAYS))"
        in text
    ), (
        "the total exposure is no longer derived from the two windows it is the sum "
        "of. A literal here is a number that stops tracking what it describes the "
        "first time either window moves."
    )


def test_the_media_bucket_carries_a_noncurrent_version_expiry() -> None:
    """The posture itself, asserted where it is set.

    Without this rule the platform's `delete_object` is a delete marker and
    nothing else. The rule is the whole of what makes `purged` true on a
    versioned bucket, and it is one `aws s3api` call somebody could remove while
    tidying and nothing would say so.
    """
    text = PROVISION.read_text()
    assert "put-bucket-lifecycle-configuration" in text
    assert '"NoncurrentVersionExpiration": {"NoncurrentDays": ${DJB_ARCHIVE_GRACE_DAYS}}' in text, (
        "the noncurrent-version expiry no longer reads the declared grace window. "
        "A hard-coded day count here is the second number this whole file exists "
        "to prevent."
    )


@pytest.mark.parametrize("path", [PROVISION, EXPORTS_MODELS])
def test_both_halves_of_the_pairing_are_where_this_test_looks(path: Path) -> None:
    """A pairing whose files moved would pass every assertion above by reading
    two empty strings; both reads assert their count, but a missing file is the
    louder failure and deserves the louder sentence."""
    assert path.is_file(), f"{path} is gone; the retention pairing has no second half."
