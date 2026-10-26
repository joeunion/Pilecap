"""The kill drive: a worker killed mid-apply, a worker restarted, four rows — not five.

    uv run python -m apps.djb_imports.tests.kill_drive

Run on a verifier box with the compose stack up (Postgres, MinIO, Temporal) and
this checkout migrated. It owns its two worker processes (`live_worker`), and
kills only them, by pid:

1. seeds a fresh tenant and its owner through the services (a unique slug per run);
2. files a five-row CSV in the REAL widget importer's header (row 3 invalid) as a
   document through the files seam — the product's `apps/example/importers.py`,
   never a plant under its name (both workers print which module applied, and
   the drive refuses any other);
3. stages it — `create_import` starts `ValidateImportWorkflow` on the real
   Temporal — and waits for `previewed`;
4. presses apply, waits until TWO rows are settled, and SIGKILLs the worker;
5. starts a second worker; the apply activity's heartbeat lapses, Temporal hands
   it over, and the retry resumes at the first unsettled row;
6. waits for `imported` and prints the evidence: the rows' outcomes, the widget
   count, the `example.create_widget` audit rows and their correlation ids, and
   the apply activity's attempts.

Exit 0 when the run imported exactly four widgets, each keyed by its
`external_ref`, with four audit rows, through the product's importer; 1 when it
did not; 2 when it could not look (a worker that never came up, a timeout).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django  # noqa: E402

django.setup()

from apps.accounts.services import create_user  # noqa: E402
from apps.core.actor import actor_for, system_actor  # noqa: E402
from apps.core.audit import AuditEntry  # noqa: E402
from apps.core.models import Membership  # noqa: E402
from apps.core.services import add_membership, create_tenant, root_organization  # noqa: E402
from apps.djb_imports.models import Import, ImportRow  # noqa: E402
from apps.djb_imports.services import apply_import, create_import  # noqa: E402
from apps.djb_imports.tests.live_worker import (  # noqa: E402
    ensure_bucket,
    importer_module,
    install_seam,
)
from apps.djb_imports.tests.store import stored_csv  # noqa: E402
from apps.example.models import Widget  # noqa: E402

PAUSE_SECONDS = "3"
DEADLINE_SECONDS = 240
#: The module whose importer the drive measures: the worked example's own.
PRODUCT_IMPORTER = "apps.example.importers"
#: Five rows in the real importer's header, the third refused by its row schema
#: (an empty name) — four widgets, each keyed by the id it has elsewhere.
FIVE_ROWS_ONE_BAD = (
    "external_ref,name,notes\r\n"
    "KD-1,Alpha,first\r\n"
    "KD-2,Bravo,second\r\n"
    "KD-3,,third has no name\r\n"
    "KD-4,Delta,fourth\r\n"
    "KD-5,Echo,fifth\r\n"
)


def say(line: str) -> None:
    print(f"kill_drive: {line}", flush=True)


def worker_log(n: int) -> Path:
    """Where worker `n`'s output lands — the platform's temp directory, not a fixed `/tmp`."""
    return Path(tempfile.gettempdir()) / f"kill_drive_worker_{n}.log"


def worker_importer(n: int) -> str:
    """The `importer=` a worker's banner printed, or `?` when it printed none."""
    with open(worker_log(n), encoding="utf-8", errors="replace") as log:
        for line in log:
            if line.startswith("live_worker:") and " importer=" in line:
                return line.rsplit(" importer=", 1)[1].strip()
    return "?"


def start_worker(n: int) -> subprocess.Popen[bytes]:
    log = open(worker_log(n), "wb")  # noqa: SIM115 - lives as long as the process
    worker = subprocess.Popen(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
        [sys.executable, "-m", "apps.djb_imports.tests.live_worker", PAUSE_SECONDS],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    say(f"worker {n} started pid={worker.pid} (log {worker_log(n)})")
    return worker


def wait_for(what: str, predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + DEADLINE_SECONDS
    while not predicate():
        if time.monotonic() > deadline:
            say(f"COULD NOT LOOK — timed out waiting for {what}")
            raise SystemExit(2)
        time.sleep(0.5)


def settled(run: Import) -> int:
    return ImportRow.objects.filter(run=run).exclude(outcome="").count()


def status(run: Import) -> str:
    return str(Import.objects.get(pk=run.pk).status)


def attempts(run: Import) -> list[int]:
    """The apply activity's attempt numbers, read off the run's Temporal history."""
    import asyncio

    from apps.workflows.client import get_client
    from apps.workflows.services import workflow_id

    # Built on the synchronous side: it reads the tenant row.
    apply_id = workflow_id(
        tenant=run.tenant, app="djb_imports", noun="import", key=f"{run.pk}-apply"
    )

    async def read() -> list[int]:
        client = await get_client()
        history = await client.get_workflow_handle(apply_id).fetch_history()
        return [
            event.activity_task_started_event_attributes.attempt
            for event in history.events
            if event.HasField("activity_task_started_event_attributes")
        ]

    return asyncio.run(read())


def main() -> int:
    here = importer_module()
    say(f"iter_object={install_seam()} bucket={ensure_bucket()} importer={here}")
    if here != PRODUCT_IMPORTER:
        say(f"COULD NOT LOOK — the widget importer is {here}, not {PRODUCT_IMPORTER}")
        return 2
    slug = f"kill-{uuid.uuid4().hex[:8]}"
    tenant = create_tenant(name=f"Kill drive {slug}", slug=slug, actor=system_actor())
    owner = create_user(email=f"{slug}@example.com", password="a" * 24)
    add_membership(
        user=owner,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.OWNER,
        actor=system_actor(tenant=tenant),
    )
    actor = actor_for(user=owner, tenant=tenant, org=root_organization(tenant=tenant))
    first = start_worker(1)
    second = None
    try:
        version = stored_csv(actor, FIVE_ROWS_ONE_BAD)
        run, created = create_import(
            tenant=tenant, actor=actor, kind="widget", file_version=version
        )
        say(f"staged import {run.pk} created={created} tenant={slug}")
        wait_for("previewed", lambda: status(run) == "previewed")
        run.refresh_from_db()
        say(f"previewed counts={run.counts} apply_writes={run.apply_writes}")
        apply_import(tenant=tenant, actor=actor, import_=run)
        say("apply pressed")
        wait_for("two settled rows", lambda: settled(run) >= 2)
        os.kill(first.pid, signal.SIGKILL)
        first.wait()
        killed_at = settled(run)
        say(
            f"SIGKILL worker 1 pid={first.pid} with {killed_at} row(s) settled, "
            f"widgets={Widget.objects.filter(tenant=tenant).count()}, status={status(run)}"
        )
        second = start_worker(2)
        wait_for("imported", lambda: status(run) == "imported")
        run.refresh_from_db()
    finally:
        for worker in (first, second):
            if worker is not None and worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=30)

    outcomes = list(
        ImportRow.objects.filter(run=run).order_by("row_no").values_list("row_no", "outcome")
    )
    widgets = sorted(Widget.objects.filter(tenant=tenant).values_list("name", flat=True))
    refs = sorted(Widget.objects.filter(tenant=tenant).values_list("external_ref", flat=True))
    applied_through = sorted({worker_importer(1), worker_importer(2)})
    audits = list(
        AuditEntry.objects.filter(tenant=tenant, action="example.create_widget").values_list(
            "correlation_id", flat=True
        )
    )
    tries = attempts(run)
    say(f"status={run.status} counts={run.counts} applied_at={run.applied_at}")
    say(f"rows={outcomes}")
    say(f"widgets={len(widgets)} {widgets} external_refs={refs}")
    say(f"the workers applied through {applied_through}")
    say(f"create_widget audit rows={len(audits)} correlations={sorted(set(audits))}")
    say(f"apply activity attempts={tries}")
    ok = (
        run.status == Import.Status.IMPORTED
        and len(widgets) == 4
        and refs == ["KD-1", "KD-2", "KD-4", "KD-5"]
        and applied_through == [PRODUCT_IMPORTER]
        and len(audits) == 4
        and max(tries) >= 2
    )
    say("PASS — four rows, not five" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
