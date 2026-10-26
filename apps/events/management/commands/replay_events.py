"""`manage.py replay_events` — send events again after something went wrong.

    uv run python manage.py replay_events --since 2026-08-19
    uv run python manage.py replay_events --id 0199...            # one event
    uv run python manage.py replay_events --since 2026-08-19 --failed-only --dry-run

The recovery path `architecture.md` names ("the outbox is retained;
`manage.py replay_events` is the recovery path, so a consumer must be
replay-safe"). A subscriber that was down for an afternoon, an endpoint whose
URL was wrong, a deploy that took the worker away — all of them end with events
in the outbox that nobody heard about, and this is how they are told.

**It re-enqueues; it does not deliver.** Each row goes back through
`services.enqueue_dispatch`, which is the same service `emit` uses: the same
outbox transition, the same deterministic workflow id (with the attempt number
in it, so a replay is not refused by the run the first attempt left), the same
fan-out. There is no second delivery path to drift.

It is a **door** like any other: `core.management.BaseCommand` binds
`door="shell"` and a correlation id around the whole run, so every audit row a
replay writes says where it came from, and the events it re-sends join the same
chain as the originals.

Deliberately cross-tenant: an outage is a deployment-level event, and making
somebody run this once per customer is how a recovery gets half-finished.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.management.base import CommandError
from django.utils.dateparse import parse_date, parse_datetime

from apps.core.management import BaseCommand
from apps.core.time import UTC
from apps.events import selectors, services
from apps.events.models import Outbox


def _instant_argument(raw: str) -> datetime:
    """A date or a datetime on the command line, as an aware UTC instant."""
    parsed = parse_datetime(raw)
    if parsed is None:
        day = parse_date(raw)
        if day is None:
            raise CommandError(f"{raw!r} is not a date or a datetime (try 2026-08-19).")
        parsed = datetime.combine(day, datetime.min.time())
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class Command(BaseCommand):
    help = "Re-enqueue outbox rows so their events are dispatched again."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--since", default=None, help="Only events at or after this moment.")
        parser.add_argument("--id", default=None, help="One event, by its id.")
        parser.add_argument(
            "--failed-only",
            action="store_true",
            help="Only rows that are not already dispatched.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be re-enqueued and change nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        since = _instant_argument(str(options["since"])) if options["since"] else None
        event_id: UUID | None = None
        if options["id"]:
            try:
                event_id = UUID(str(options["id"]))
            except ValueError as exc:
                raise CommandError(f"{options['id']!r} is not a UUID.") from exc
        if since is None and event_id is None:
            # Replaying everything ever emitted is almost never what somebody
            # means, and it is not something to discover after the fact.
            raise CommandError("Give --since or --id; replaying the whole outbox is not a default.")

        rows = selectors.list_outbox_to_replay(since=since, event_id=event_id)
        if options["failed_only"]:
            rows = rows.exclude(status=Outbox.Status.DISPATCHED)

        replayed = 0
        for outbox in rows:
            event = outbox.event
            self.stdout.write(
                f"{event.occurred_at.isoformat()}  {event.tenant.slug:20}  "
                f"{event.name:40}  {event.pk}  [{outbox.status}]"
            )
            if options["dry_run"]:
                continue
            services.enqueue_dispatch(tenant=event.tenant, event_id=event.pk)
            replayed += 1

        if options["dry_run"]:
            self.stdout.write(f"dry run: {rows.count()} row(s) would be re-enqueued")
            return
        self.stdout.write(f"re-enqueued {replayed} row(s)")
