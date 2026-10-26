"""`manage.py webhook_endpoints --refused` — the active endpoints no delivery will reach.

    uv run python manage.py webhook_endpoints --refused

One row per active endpoint whose URL `apps.events.targets` refuses today, as
`<tenant slug>  <endpoint id>  <class>`, then `<n> refused`. The URL itself is
not printed: its query string can carry a subscriber's token. Deliveries to
these rows already fail closed (ADR events-5); this is the operator's list
at upgrade, deployment-wide like `replay_events`.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import CommandError

from apps.core.management import BaseCommand
from apps.events import selectors, targets


class Command(BaseCommand):
    help = "List the active webhook endpoints whose target is refused."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--refused",
            action="store_true",
            help="Every active endpoint whose URL is refused, with its tenant and class.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["refused"]:
            raise CommandError("Give --refused; it is the one question this command answers.")
        refused = 0
        for endpoint in selectors.list_active_endpoints_everywhere():
            found = targets.target_class(endpoint.url)
            if found is None:
                continue
            refused += 1
            self.stdout.write(f"{endpoint.tenant.slug}  {endpoint.pk}  {found}")
        self.stdout.write(f"{refused} refused")
