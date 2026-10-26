"""`manage.py sso_domains [--unverified]` — the domain claims, and which route (ADR ident-10)."""

from __future__ import annotations

from typing import Any

from apps.accounts.models import SsoDomain
from apps.core.management import BaseCommand


class Command(BaseCommand):
    help = "List email-domain claims across tenants; --unverified lists the ones that route nobody."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--unverified",
            action="store_true",
            help="Only the claims no operator has verified yet.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # rule-8: the operator's read across every tenant, beside `verify_sso_domain`.
        claims = SsoDomain.objects.get_queryset().select_related("tenant", "connection")
        if options.get("unverified"):
            claims = claims.filter(verified_at__isnull=True)
        rows = list(claims.order_by("domain"))
        if not rows:
            self.stdout.write(
                "no unverified domain claims" if options.get("unverified") else "no domain claims"
            )
            return
        for row in rows:
            if row.verified_at is None:
                state = (
                    "unverified  -> manage.py verify_sso_domain "
                    f"--tenant {row.tenant.slug} --domain {row.domain}"
                )
            else:
                state = f"verified {row.verified_at.isoformat()}"
            self.stdout.write(
                f"{row.domain}  tenant={row.tenant.slug}  connection={row.connection.name}  {state}"
            )
