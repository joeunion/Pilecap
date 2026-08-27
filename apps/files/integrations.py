"""Does this deployment have object storage — really, right now?

The census's discovered hook (`apps/core/integrations.py`), answered for the one
external service this app owns. Four surfaces read it and none of them is edited
to add this file: `scripts/setup.sh`'s epilogue, `manage.py integrations`,
`deploy/release.sh --wall` and the standing prober all read `census()`, and
`census()` finds this module because it has the conventional name.

## Why the storage row is THIS app's and could not be core's

An earlier attempt tried to declare it in `apps/core/integrations.py` and **house rule
48 refused the module by name**. A census row that says "no object storage here"
owes a REMEDY — what to type — and what there is to type is the bucket setting,
which rule 48 fences to `apps/files/storage.py` and `config/settings/`. That is
the platform-concern boundary doing its job rather than a gap: the platform owns
the MECHANISM (the value type, the registry, the four surfaces, the exit codes)
and each app owns the FACT of whether its own integration is real. So the fact is
declared here, and the words are `storage.CONFIGURE_BUCKET_REMEDY` — held in the
seam, because the seam is the module allowed to hold them.

Nothing in this file imports boto3, names a bucket setting, signs a URL or reads
an object. It asks `apps.files.storage` two questions and prints the answers.

## LIVE, not declared, and what that costs

`probe="live"` here means what the vocabulary says it means: something outside
this process answered while the census ran. The probe is `head_bucket` — the
cheapest call S3 has that proves reachability *and* that this credential may see
this bucket, and it writes nothing. `apps/core/health.py` makes the identical
call for `/readyz`, and the duplication is deliberate rather than a second
opinion: `/readyz` answers "is this replica able to serve" per request, and the
census answers "is this deployment wired up" on demand and at release time. They
can honestly disagree — a bucket named but unreachable is a `false` readiness
member and a `not_configured` census row, and both statements are true.

## Three answers and the one that is missing

`CONFIGURED` — a bucket is named and it answered.
`NOT_CONFIGURED` — no bucket is named, or one is named and the store refused us.
Both are reported with the remedy that fits, and the second is reported as a
LIVE probe: we looked.

**There is deliberately no `FAKE` row here**, and the reason is worth stating
because `FAKE` is the status the census exists for. The shape that would earn it
is the stand-in that succeeds — `STORAGES` staying on the local filesystem, so
uploads land on a container disk that disappears at the next deploy, silently.
That door is now closed twice over: `bucket_name()` raises rather than inventing
a name, so nothing in this app writes anywhere without a bucket, and house rule
48's fifth clause fences `django.core.files.storage` out of every module under
`apps/` — which is exactly the door `apps/exports` walked through before it was closed. With
no path left that quietly succeeds, an absent bucket is an absence, and calling
it a fake would be inventing a danger the tree no longer has.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from apps.core.integrations import (
    PROBE_DECLARED,
    PROBE_LIVE,
    Integration,
    IntegrationRegistry,
    IntegrationStatus,
)
from apps.files import storage

SOURCE = "apps/files/integrations.py"

#: The slug a runbook, an alert and the deploy wall all name. Chosen once; it
#: does not move with the title.
KEY = "object-storage"

TITLE = "Object storage"


def register(registry: IntegrationRegistry) -> None:
    """The discovered hook. One row, live-probed, with the remedy that fits."""
    try:
        name = storage.bucket_name()
    except ImproperlyConfigured:
        registry.declare(
            Integration(
                key=KEY,
                title=TITLE,
                status=IntegrationStatus.NOT_CONFIGURED,
                detail=(
                    "no bucket is named, so this deployment stores no documents: every "
                    "upload, download and export refuses at the seam and /readyz carries "
                    "no storage member."
                ),
                remedy=storage.CONFIGURE_BUCKET_REMEDY,
                # `declared` and not `live`: nothing was contacted, because there
                # was nothing to contact. Claiming a live probe here would be the
                # weaker claim dressed as the stronger one.
                probe=PROBE_DECLARED,
            ),
            source=SOURCE,
        )
        return

    try:
        storage.head_bucket()
    except storage.StorageUnreadable as refusal:
        registry.declare(
            Integration(
                key=KEY,
                title=TITLE,
                status=IntegrationStatus.NOT_CONFIGURED,
                # The refusal already names the bucket — `StorageUnreadable`'s
                # messages all do — so this sentence says what the failure MEANS
                # rather than repeating it. `name` is deliberately unused here
                # and is read below, where it is the whole of the good news.
                detail=f"a bucket is named and it did not answer: {refusal}",
                remedy=storage.UNREACHABLE_BUCKET_REMEDY,
                probe=PROBE_LIVE,
            ),
            source=SOURCE,
        )
        return

    registry.declare(
        Integration(
            key=KEY,
            title=TITLE,
            status=IntegrationStatus.CONFIGURED,
            detail=f"bucket {name!r} answered a HEAD with this deployment's own credentials.",
            probe=PROBE_LIVE,
        ),
        source=SOURCE,
    )
