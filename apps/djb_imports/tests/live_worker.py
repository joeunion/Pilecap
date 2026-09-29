"""The stock worker, a pause before each row. **The kill drive's worker.**

    uv run python -m apps.djb_imports.tests.live_worker [<seconds before each row settles>]

`apps.workflows.worker.run()` unchanged — the same client, the same discovered
workflows and activities, the same task queue this checkout derives, and the
REAL widget importer the discovery walk finds (`apps/example/importers.py`) —
with ONE thing put in place first: a pause before each row settles
(`zzz_slow_rows.py`), so the drive can kill it mid-apply. Nothing is planted
under an importer's name; the worker prints which module the widget importer's
`apply` comes from, and the drive refuses a run whose worker applied through
anything but the product's own. The file is read through the files seam's own
server-side stream (`files.storage.iter_object`), and the worker prints that it
is.

Test code: outside house rule 48 by construction (`tests/` is not walked), and
never imported by anything shipped.
"""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("DJB_SERVICE_NAME", "worker")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from apps.djb_imports.selectors import get_importer  # noqa: E402
from apps.djb_imports.tests.zzz_slow_rows import slow_rows  # noqa: E402
from apps.files import storage as files_storage  # noqa: E402


def ensure_bucket() -> str:
    """This checkout's own bucket, named and present — the drive's two processes agree."""
    if not settings.AWS_STORAGE_BUCKET_NAME:
        settings.AWS_STORAGE_BUCKET_NAME = files_storage.derived_bucket_name()
    return files_storage.create_bucket_if_absent()


def install_seam() -> str:
    """Which `iter_object` this process runs with. The files seam's own, always.

    The double this drive carried while the seam was not yet on the tree is
    gone; this stays so both processes print what they read through.
    """
    return "real" if callable(getattr(files_storage, "iter_object", None)) else "absent"


def importer_module(kind: str = "widget") -> str:
    """The module the discovered importer's `apply` comes from — the product's, or a plant's."""
    importer = get_importer(kind)
    return "absent" if importer is None else str(importer.apply.__module__)


def main() -> None:
    pause = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    slow_rows(pause)
    seam = install_seam()
    bucket = ensure_bucket()
    print(
        f"live_worker: pid={os.getpid()} queue={settings.TEMPORAL_TASK_QUEUE} "
        f"iter_object={seam} bucket={bucket} pause={pause}s importer={importer_module()}",
        flush=True,
    )
    from apps.workflows.worker import run

    asyncio.run(run())


if __name__ == "__main__":
    main()
