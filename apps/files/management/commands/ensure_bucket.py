"""`manage.py ensure_bucket` — this checkout's object-storage bucket, made and named.

    uv run python manage.py ensure_bucket
    djb-my-worktree-8eea9820

**It prints the bucket name on stdout and nothing else**, because a script reads
that: `scripts/setup.sh` captures it and writes `AWS_STORAGE_BUCKET_NAME` into
`.env` with it. Everything a human wants to read — created or already there,
where — goes to stderr, so a redirect into a variable never picks up prose.

**Why a checkout needs its own bucket at all** is `files.storage`'s
`derived_bucket_name`: agents build in parallel worktrees against one compose
MinIO, and two of them writing `t/<tenant>/` into one bucket would see each
other's objects — the same collision `DATABASE_NAME` solves for Postgres, with
the same fix (a name derived from the checkout's own path). A name already
configured WINS, exactly as `DATABASE_NAME`'s does, so a deployment pointing at a
real S3 bucket gets that bucket checked rather than a derivation invented over
the top of it.

**Creating is this door's job and no other's.** The storage seam refuses a
deployment that has named no bucket and never invents one (`storage.bucket_name`);
a bucket appears because a person, or a script a person ran, asked for one here.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import CommandError

from apps.core.management import BaseCommand
from apps.files import storage


class Command(BaseCommand):
    help = "Create this checkout's object storage bucket if it is absent, and print its name."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            name = storage.create_bucket_if_absent()
        except Exception as failure:  # noqa: BLE001 - re-raised as the shell's own error
            raise CommandError(
                "could not reach the object store to make sure a bucket exists: "
                f"{failure}\n"
                "On a laptop or in a worktree that is the compose MinIO — "
                "`docker compose up -d minio` — and the endpoint the app dials is "
                "AWS_S3_ENDPOINT_URL in .env. Nothing was written; /readyz will carry "
                "no `storage` member until a bucket is named."
            ) from failure
        self.stderr.write(f"object storage bucket ready: {name}")
        self.stdout.write(name)
