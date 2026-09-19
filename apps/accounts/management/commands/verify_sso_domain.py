"""`manage.py verify_sso_domain` — the act that makes a domain claim route.

    uv run python manage.py verify_sso_domain --tenant acme --domain acme.com

**Why this exists** (a domain claim routes nothing until it is verified). Any administrator of any
tenant can claim
any email domain through `/api/v1/auth/sso-connections/`, and until R2-F1 that
claim captured the platform sign-in for everybody at that domain: a person who
already belonged somewhere else was refused outright, and a person who belonged
nowhere was absorbed into the claimant, their standing invitation elsewhere
quietly dropped. Both were driven over the wire. The fix is that a claim
reserves a name and routes nobody until somebody outside the tenant says the
tenant really owns the domain — and this command is that somebody.

**Why a shell door and not a route.** The tenant asking to be trusted cannot be
the party that says it is trusted. The persona is the deployment's operator, at
an altitude no tenant holds, beside `bootstrap_tenant` and `unlink_identity`;
ssh is the credential, and the audit row carries the operator's `system` actor
and the shell's own door value.

**It writes nothing itself** (house rule 10). The single write is
`services.verify_sso_domain`, which authorizes, locks the row, sets
`verified_at` and leaves the audit row; this command resolves rows and prints.

**Every refusal exits non-zero, and the two kinds differ.** A tenant slug that
names nobody is exit **2** — could not look. A domain that belongs to a
different tenant than the one typed is exit **1** — it looked, and refused —
and the refusal deliberately does NOT say whose it is: this is a terminal, but
the sentence is the same register the login page uses, because "which tenant
owns example.com" is not a question this product answers to whoever asks.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import CommandError

from apps.accounts.models import SsoDomain
from apps.accounts.services import verify_sso_domain
from apps.core import context
from apps.core.actor import system_actor
from apps.core.management import BaseCommand
from apps.core.models import Tenant


class Command(BaseCommand):
    help = "Confirm that a tenant owns an email domain it claims, so the claim routes."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--tenant", required=True, help="The tenant's slug.")
        parser.add_argument("--domain", required=True, help="The domain to verify.")

    def handle(self, *args: Any, **options: Any) -> None:
        slug = str(options.get("tenant") or "").strip().lower()
        domain = str(options.get("domain") or "").strip().lower().lstrip("@")

        tenant = Tenant.objects.filter(slug=slug).first()
        if tenant is None:
            # COULD NOT LOOK — exit 2. An operator who mistyped a slug and read
            # a refusal would go looking for a permission problem.
            raise CommandError(f"No tenant here has the slug {slug!r}.", returncode=2)

        claim = SsoDomain.objects.claim(domain)
        if claim is None:
            raise CommandError(f"Nobody claims {domain}.")
        if claim.tenant_id != tenant.pk:
            # Says that it is not this tenant's, and not whose it is. A terminal
            # is not a reason to answer a question the front door refuses to.
            raise CommandError(f"{domain} is not claimed by {slug}.")

        with context.bound(tenant_id=str(tenant.pk), actor_kind="system"):
            already = claim.verified_at is not None
            row = verify_sso_domain(
                tenant=tenant,
                actor=system_actor(tenant),
                connection=claim.connection,
                domain=domain,
            )

        if already:
            # Not a refusal: the state the operator asked for is the state that
            # holds, so this is exit 0 and says so plainly.
            self.stdout.write(f"already verified: {row.domain} for {slug}")
            return
        self.stdout.write(f"verified {row.domain} for {slug} (connection {claim.connection.name})")
