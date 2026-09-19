"""`manage.py sync_workforce_idp` — put the workforce Google door into Zitadel.

    uv run python manage.py sync_workforce_idp

The deployment's own identity configuration, materialised the same way a
customer's is: a service records the intent, a durable run reaches the
management API, and `apps/accounts/zitadel.py` is the only thing that speaks to
it (house rule 27). That is ADR ident-6's whole claim — **one way identity
configuration reaches Zitadel** — and a workforce door clicked into the console
by hand would have been the exception that made it untrue.

**It imports no Zitadel client**, and that is the shape rather than an accident:
this is a door (house rule 10), doors call services, and the management call
happens in an activity where a hang is a retry instead of a shell that never
comes back. `zitadel_seed` and `zitadel_audit` are the two commands that *do*
import the client, because they are read-and-report and one-shot setup; this one
asks for durable work and waits for nothing.

**`--tenant` is optional now, and it no longer decides where the run goes.**
It used to be required, and the module
docstring used to explain why: the provider belongs to the installation and to
no customer, but `workflows.WorkflowRun` was tenant-scoped, so the run had to
borrow somebody's ledger. ADR workflows-3 made that model the platform-wide run
ledger, so the run is recorded with **no tenant** under
`platform:accounts:identity_config:<key>` and no customer's ledger carries a row
about the deployment's Google credentials.

What the flag buys is **which ledger the audit row lands in, not whether there
is one** — this paragraph used to claim otherwise. `AuditEntry.tenant` is
nullable since ADR core-8 (`core` migration 0013) and `@service` audits on the
declaration, so `sync_workforce_identity_config` — which takes a keyword-only
`tenant` — leaves a row on every call. Pass `--tenant` and the ask is audited in
that workspace, as the one the operator was acting in; omit it and the row joins
the platform population with `tenant` NULL, readable through
`AuditEntry.objects.for_platform()` and through no customer's ledger. The gap
this paragraph used to name is closed.

**Who may.** `deployment.configure` — a superuser, not a tenant's owner
(`apps/accounts/policies.py` says why). `--as` names them, so the audit row
carries a person rather than "the shell".
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.accounts.services import sync_workforce_identity_config
from apps.core.actor import actor_for, system_actor
from apps.core.exceptions import DomainError
from apps.core.management import BaseCommand
from apps.core.models import Tenant


class Command(BaseCommand):
    help = "Materialise this deployment's workforce Google provider in Zitadel."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--tenant",
            default=None,
            help=(
                "Optional tenant slug to audit this ask in. The run itself is the "
                "deployment's and is recorded with no tenant; see the module docstring."
            ),
        )
        parser.add_argument(
            "--as",
            dest="acting_email",
            default=None,
            help="Superuser to attribute this to. Omit to act as the system.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        tenant: Tenant | None = None
        if options["tenant"]:
            slug = str(options["tenant"]).strip().lower()
            tenant = Tenant.objects.filter(slug=slug).first()
            if tenant is None:
                # A named tenant that does not exist is still a refusal: the
                # operator asked for the ask to be audited somewhere specific,
                # and silently auditing it nowhere would answer a question they
                # did not ask.
                raise CommandError(f"No tenant with slug {slug}.")

        email = options["acting_email"]
        if email:
            user = User.objects.filter(email=str(email).strip().lower()).first()
            if user is None:
                raise CommandError(f"No user with email {email}.")
            actor = actor_for(user=user, tenant=tenant, kind="human")
        else:
            # Nobody clicked this. `core.authz.allows` lets the system past
            # before any policy runs, which is right and is also why naming a
            # person with `--as` is the better habit on a shared deployment.
            actor = system_actor(tenant)

        try:
            run_key = sync_workforce_identity_config(tenant=tenant, actor=actor)
        except DomainError as error:
            # The refusals here are for a person at a terminal — no Google
            # credentials, or an empty domain list, which means the door is off.
            # A traceback would bury the sentence that fixes it.
            raise CommandError(error.detail) from error

        self.stdout.write(f"asked    workforce provider  ({run_key})")
        self.stdout.write(
            self.style.WARNING(
                "The run materialises it. Watch it in Temporal, or read the result "
                "with `manage.py zitadel_audit`."
            )
        )
