"""`manage.py storage_audit` — does the bucket still say what our rows say?

    uv run python manage.py storage_audit
    uv run python manage.py storage_audit --tenant acme
    uv run python manage.py storage_audit --digest      # read every object back

**The honest half of house rule 48**, and its sibling `zitadel_audit` is the
shape (rule 27). The enforceable half is the wall: no module under `apps/`
outside `apps/files/storage.py` reaches the object store, so nothing *in this
codebase* writes an object behind the services' back. A check cannot see a
bucket. Rule 48's own `does_not_cover` says so in as many words — *"THE BUCKET'S
OWN STATE AND POLICY are the declared blind spot this rule is one half of … the
partial answer is `manage.py ensure_bucket` and `storage_audit`, not a
check."* This is that partial answer: a read-only report of where the two
disagree.

**It changes nothing, and that is a property rather than a promise.** Every call
it makes goes through the four read-only functions in the seam's own audit
section (`head_bucket`, `walk_objects`, `retention_posture`, `sha256_of`), and
there is no write verb in that section for this command to reach.

## What it compares

**The retention posture (the live half).** `deploy/provision.sh` sets a
lifecycle configuration on the media bucket and `apps/core/tests/
test_archive_retention.py` pins the numbers in that script against
`apps/exports`' own declaration — **by reading the script as text.** Both halves
can agree perfectly while the actual bucket carries no rule at all, and then
every instrument on this tree reports an archive purged while a copy of a
tenant's whole database sits in the bucket as a noncurrent version, forever.
Versioning is what makes the rule load-bearing, nothing announces the day
somebody turns versioning on, and this section is what announces it.

**The objects against the rows.** Three disagreements, each its own line:

* **missing** — a `STORED` version whose object is not there. The row quotes a
  digest that nothing can be checked against and a download will 404.
* **orphan** — an object under a key no row claims. Bytes nobody can reach,
  nobody will purge, and somebody is paying for.
* **size drift** — the store's own byte count differs from what `record_stored`
  measured. With `--digest` the object is read back and the hash compared too,
  which is the only comparison that catches a *changed* object rather than a
  resized one, and which costs a full read of every object in the deployment.

A `PENDING` version's key is a special case and is reported apart from all
three: an object at one is an upload that landed and has not been finalized, and
an absent one is a ticket nobody used. Neither is drift — `SweepPendingUploads`
owns that population — and calling either one would make this report cry wolf on
every busy deployment.

## Exit status

* **0** — the bucket and the rows agree.
* **1** — they disagree. Every disagreement is printed. Nothing was changed.
* **2** — **it could not look.** No bucket is configured, the store would not
  answer, or a policy could not be read. "I could not look" is not "I looked and
  it is not there", and this command refuses to turn the first into the second;
  the instrument checklist's line, `manage.py integrations`' convention and the
  gate's own semantics, and it outranks every other verdict.

`zitadel_audit` never exits 2 and this one does, which is a real difference
rather than an inconsistency: that command refuses at the top when Zitadel is
not configured, so by the time it is comparing anything it can always look.
This one walks a bucket that can go away underneath it.

## What it cannot see

* **It is POINT-IN-TIME.** The walk and the row read are not one transaction and
  could not be — an object deleted between the two is reported as missing, and a
  version finalized between them is reported as an orphan. A single line in a
  report from a busy deployment is a thing to re-run before it is a thing to act
  on; a line that persists is a finding.
* **The store's own history.** A noncurrent version, a delete marker, an object
  restored from one — the walk lists current objects, so the posture section is
  the only thing here that knows versioning exists at all.
* **A bucket policy, an ACL or a public-read grant**, which are the rest of rule
  48's declared blind spot and are not this command's subject. It reports what
  happens to a deleted object because that is the half that makes a *lifecycle
  declaration in this tree* true or false.
* **Anything outside this deployment's one bucket.** `bucket_name()` is the
  whole of what it looks at, per checkout and per worker.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured

from apps.core.management import BaseCommand
from apps.core.models import Tenant
from apps.files import storage
from apps.files.models import FileVersion

#: How wide the label column is, so a skim reads down it. The words are the
#: report's whole vocabulary and there are five.
_WIDTH = len("size drift")


class Command(BaseCommand):
    help = (
        "Report where this deployment's object storage and its file rows disagree, "
        "and whether the bucket's own retention posture makes `purged` true. "
        "Changes nothing."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--tenant",
            default="",
            help="Only audit one tenant's objects and rows, by slug.",
        )
        parser.add_argument(
            "--digest",
            action="store_true",
            help=(
                "Read every stored object back and compare its SHA-256, not just its "
                "size. Catches a CHANGED object; costs a full read of the bucket."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = self._named_tenant(str(options["tenant"]).strip().lower())

        try:
            bucket = storage.bucket_name()
            storage.head_bucket()
        except ImproperlyConfigured as refusal:
            # Not a clean report and not drift: there is no bucket to have an
            # opinion about. Exit 2 for the same reason `manage.py integrations`
            # uses it — an instrument that answered 0 here would be reporting a
            # deployment with no object storage as one whose storage agrees.
            self.stderr.write(self.style.ERROR(str(refusal)))
            raise SystemExit(2) from refusal
        except storage.StorageUnreadable as refusal:
            self.stderr.write(self.style.ERROR(str(refusal)))
            self.stderr.write(storage.UNREACHABLE_BUCKET_REMEDY)
            raise SystemExit(2) from refusal

        self.stdout.write(f"bucket          {bucket}")
        if tenant is not None:
            self.stdout.write(f"scoped to       {tenant.slug} ({storage.tenant_prefix(tenant)})")
        self.stdout.write("")

        drift = self._report_retention()
        self.stdout.write("")
        drift += self._report_objects(tenant=tenant, digests=bool(options.get("digest")))

        self.stdout.write("")
        if drift:
            self.stdout.write(self.style.WARNING(f"{drift} disagreement(s). Nothing was changed."))
            # `SystemExit` rather than `CommandError`: the report above already
            # said everything, and a traceback-shaped error on top of it would
            # read as a crash rather than as a verdict. `zitadel_audit`'s form.
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("The bucket agrees with every row. Nothing changed."))

    # --- the sections ---------------------------------------------------------

    def _named_tenant(self, slug: str) -> Tenant | None:
        """The tenant to narrow to, or `None` for the whole deployment.

        Resolved before anything is read so that a typo is an error and not a
        clean report over an empty set — the shape a scoped audit fails in
        silently, and the one worth spending a query on.
        """
        if not slug:
            return None
        found = Tenant.objects.filter(slug=slug).first()
        if found is None:
            self.stderr.write(self.style.ERROR(f"no tenant has the slug {slug!r}."))
            raise SystemExit(2)
        return found

    def _report_retention(self) -> int:
        """What the bucket does with a deleted object. Returns disagreements.

        The pairing's live half. `apps/core/tests/test_archive_retention.py`
        reads `deploy/provision.sh` as text and proves the two declared numbers
        agree; this reads the bucket and proves the declaration reached it.
        """
        try:
            posture = storage.retention_posture()
        except storage.StorageUnreadable as refusal:
            # The one place in this command where a refusal is NOT fatal by
            # itself — but it is still exit 2, immediately, because a report
            # that skipped the posture section and then printed a green verdict
            # would be the exact instrument failure this whole file is shaped
            # against. Said out loud rather than left to the exit code.
            self.stderr.write(self.style.ERROR(str(refusal)))
            self.stderr.write(
                "The retention posture is the half of house rule 31 that lives below "
                "the ORM; a report that could not read it is not a report that it is "
                "fine. Nothing here is a judgment about this bucket."
            )
            raise SystemExit(2) from refusal

        rules = ", ".join(name for name in posture.rule_ids if name) or "none"
        self.stdout.write(f"versioning      {'on' if posture.is_versioned else 'off'}")
        self.stdout.write(f"lifecycle rules {rules}")

        if not posture.is_versioned:
            self.stdout.write(
                "retention       a delete is a delete on this bucket, so the platform's "
                "purge really removes the bytes and no lifecycle rule is owed."
            )
            return 0

        if posture.keeps_deleted_objects_forever:
            self.stdout.write(
                self.style.WARNING(
                    "DRIFT           versioning is ON and no enabled rule expires a "
                    "noncurrent version. Every object this platform reports as purged "
                    "is still in this bucket, behind a delete marker, forever — house "
                    "rule 31's `purged` is false below the ORM."
                )
            )
            self.stdout.write(
                "                remedy: deploy/provision.sh sets the posture "
                "(NoncurrentVersionExpiration at DJB_ARCHIVE_GRACE_DAYS); run it for "
                "this environment, or apply the same lifecycle configuration to this "
                "bucket by hand."
            )
            return 1

        self.stdout.write(
            f"retention       noncurrent versions expire after "
            f"{posture.noncurrent_expiry_days} day(s) — the platform purges first and "
            "the bucket lets go after, which is the direction the pairing needs."
        )
        if posture.abort_incomplete_after_days is None:
            # Reported and NOT counted as drift: abandoned parts are a cost and
            # an invisibility, not a retention lie, and `provision.sh` is where
            # the two rules ride together rather than where either depends on
            # the other.
            self.stdout.write(
                "note            no rule aborts incomplete multipart uploads; failed "
                "uploads leave parts that are billed and appear in no listing."
            )
        return 0

    def _report_objects(self, *, tenant: Tenant | None, digests: bool) -> int:
        """The bucket walked against the rows. Returns disagreements.

        The rows are read with the bare manager on purpose and the reason is the
        same one `walk_objects` gives for being unbelted: this is a
        deployment-wide instrument run from a shell, and the disagreement it most
        needs to find is a row or an object that no tenant's scoped read would
        return. Narrowing is offered as `--tenant` and applied to BOTH sides
        together, so the two halves of every comparison always cover the same
        ground.
        """
        prefix = storage.tenant_prefix(tenant) if tenant is not None else ""
        rows = FileVersion.objects.all()
        if tenant is not None:
            rows = rows.filter(tenant=tenant)
        # The tenant row is only ever needed to belt `sha256_of`, so it is joined
        # only when `--digest` asks for it: a deployment-wide walk that fetched a
        # tenant per version would be an N+1 in an instrument.
        rows = rows.select_related("tenant") if digests else rows

        stored: dict[str, FileVersion] = {}
        pending: dict[str, FileVersion] = {}
        for version in rows.iterator():
            target = stored if version.status == FileVersion.Status.STORED else pending
            target[version.key] = version

        try:
            objects = {found.key: found for found in storage.walk_objects(prefix=prefix)}
        except storage.StorageUnreadable as refusal:
            # The walk is lazy, so the store can stop answering half way through
            # one. A partial listing would turn every object it did not reach
            # into an "orphan" line — the loudest possible way to report an
            # outage as data loss.
            self.stderr.write(self.style.ERROR(str(refusal)))
            raise SystemExit(2) from refusal
        self.stdout.write(f"objects         {len(objects)} under {prefix or 'the whole bucket'}")
        self.stdout.write(f"rows            {len(stored)} stored, {len(pending)} pending")
        self.stdout.write("")

        drift = 0
        for key, version in sorted(stored.items()):
            found = objects.get(key)
            if found is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"{'missing'.ljust(_WIDTH)}  {key} — version {version.pk} is stored and "
                        "the object is not there; a download of it will 404 and its digest "
                        "checks against nothing."
                    )
                )
                drift += 1
                continue
            if version.size_bytes is not None and found.size_bytes != version.size_bytes:
                self.stdout.write(
                    self.style.WARNING(
                        f"{'size drift'.ljust(_WIDTH)}  {key} — the store holds "
                        f"{found.size_bytes} bytes and the row records {version.size_bytes}."
                    )
                )
                drift += 1
                continue
            if digests:
                drift += self._compare_digest(key=key, version=version)

        for key in sorted(objects):
            if key in stored or key in pending:
                continue
            self.stdout.write(
                self.style.WARNING(
                    f"{'orphan'.ljust(_WIDTH)}  {key} — an object no version row claims. "
                    "Nothing will ever read it and nothing will ever purge it."
                )
            )
            drift += 1

        # Not drift, and printed anyway: an operator looking at a bucket that is
        # bigger than the rows explain should be able to see how much of the gap
        # is uploads in flight before deciding anything is wrong.
        landed = sum(1 for key in pending if key in objects)
        if pending:
            self.stdout.write(
                f"{'pending'.ljust(_WIDTH)}  {len(pending)} allocated key(s), {landed} with an "
                "object waiting for finalize. Neither is drift; SweepPendingUploads owns them."
            )
        return drift

    def _compare_digest(self, *, key: str, version: FileVersion) -> int:
        """Read the object back and compare what we measured. `--digest` only."""
        measured = storage.sha256_of(tenant=version.tenant, key=key)
        if measured.sha256 == version.sha256:
            return 0
        self.stdout.write(
            self.style.WARNING(
                f"{'digest'.ljust(_WIDTH)}  {key} — the object hashes to "
                f"{measured.sha256[:12]}… and the row records {version.sha256[:12]}…. "
                "The bytes are not the bytes this platform witnessed."
            )
        )
        return 1
