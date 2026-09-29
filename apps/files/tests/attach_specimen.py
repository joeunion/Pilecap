"""How a test files a document against any subject — this app's attach specimen.

**The hook core's attachment conformance tests import.** Every app that answers
for `"*"` in its `merge_repointers.py` ships one of these, at this path, with this
signature, so the family's own tests can plant "something attached to this row"
without knowing what a document is: the merge conformance test attaches, merges
and asserts the repointer's promises, and the landing test attaches against an
org-scoped subject and a tenant-wide one and asserts where the row lands. An app
that answers for `"*"` without one fails those tests by name rather than being
skipped.

It files through the real service, `create_file(subject=…)` — the same subject
resolution, the same landing law (the subject's organization; the acting hat for
a subject that has none) and the same audit row a caller's filing gets — never by
building the row by hand, because a specimen that bypassed the service would
prove the conformance of a document nobody can make.

The subject's model must list `files` in its `attachments` for the filing to be
taken; declaring that is the calling test's business, not this helper's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.test import override_settings

from apps.core.authz import kind_of
from apps.files import storage
from apps.files.services import create_file

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.actor import Actor
    from apps.core.models import Tenant
    from apps.files.models import StoredFile


def attach(*, tenant: Tenant, actor: Actor, subject: Any) -> StoredFile:
    """File one document against `subject` as `actor`, and answer the document.

    The actor must be a person (a document records who filed it) wearing a hat
    that can reach the subject. Filing mints an upload link, which needs a bucket
    NAME and no bucket (the signature is a local computation): when the calling
    test configured none, this checkout's derived name is used for the one call.
    """
    kind = kind_of(type(subject))
    reference = f"{kind}:{subject.pk}"

    def filed() -> StoredFile:
        return create_file(
            tenant=tenant,
            actor=actor,
            filename="attached-specimen.pdf",
            content_type="application/pdf",
            size_bytes=10,
            purpose="upload",
            subject=reference,
        ).file

    if settings.AWS_STORAGE_BUCKET_NAME:
        return filed()
    with override_settings(AWS_STORAGE_BUCKET_NAME=storage.derived_bucket_name()):
        return filed()
