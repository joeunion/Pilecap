"""`manage.py grant_staff` — make somebody staff, once, with a record of it.

    uv run python manage.py grant_staff --email person@example.com --as you@example.com

**This is the road that replaces `createsuperuser`** (ADR ident-4).
Django's command prompts for a password and writes it into `User.password`,
which is the second credential store this deployment does not keep — every
interactive authentication happens at the identity platform — and it hands out
`is_superuser` alongside `is_staff` and leaves no record that anybody did it.
`is_staff` is the flag that opens `/admin/`, a door onto every tenant's rows, so
the grant is a service with a policy and an audit row like every other write
here (house rules 10 and 13).

**It imports no Zitadel client and asks it nothing**, deliberately: being staff
is a fact about *our* row and not about the person's credential. Somebody who
should stop being able to sign in at all is `deactivate_user` or `erase_user`,
both of which clear `is_staff` on the way past.

**Who may.** `deployment.configure` — a superuser, not a tenant's owner
(`apps/accounts/policies.py` says why). `--as` names them, so the audit row
carries a person rather than "the shell"; omit it and the act is the system's,
which `core.authz.allows` lets past before any policy runs.

**Where the row lands.** With no tenant, in the platform population —
`AuditEntry.objects.for_platform()`, and no customer's ledger. The service
declares a keyword-only `tenant` because that declaration is what makes
`@service` audit at all (ADR core-8); there is no `--tenant` flag because there
is no workspace whose ledger this belongs in.

**The exits are the shell door's three, as everywhere here.** 0 the flag is set ·
1 somebody looked and said no (the policy refused, or the account is switched
off) · 2 could not look at all (no such address). An operator who mistyped an
address must not read a refusal and believe they were denied.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.accounts.services import grant_staff
from apps.core.actor import actor_for, system_actor
from apps.core.exceptions import DomainError
from apps.core.management import BaseCommand


class Command(BaseCommand):
    help = (
        "Let somebody open /admin/: the one audited road to is_staff. "
        "It replaces `createsuperuser`, which writes a password into the second "
        "credential store this deployment does not keep (ADR ident-4), hands out "
        "is_superuser too, and records nothing."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--email",
            required=True,
            help="The person to make staff.",
        )
        parser.add_argument(
            "--as",
            dest="acting_email",
            default=None,
            help="Superuser to attribute this to. Omit to act as the system.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        email = str(options["email"]).strip().lower()
        person = User.objects.filter(email=email).first()
        if person is None:
            # Could not look, not refused: an operator who mistyped an address
            # and read exit 1 would believe the deployment had denied them.
            raise CommandError(f"No user with email {email}.", returncode=2)

        acting = options["acting_email"]
        if acting:
            actor_user = User.objects.filter(email=str(acting).strip().lower()).first()
            if actor_user is None:
                raise CommandError(f"No user with email {acting}.", returncode=2)
            actor = actor_for(user=actor_user, tenant=None, kind="human")
        else:
            actor = system_actor()

        try:
            granted = grant_staff(user=person, actor=actor, tenant=None)
        except DomainError as error:
            # A person at a terminal reads the sentence, not a traceback: the
            # two refusals here are "you may not" and "that account is off", and
            # both have a next move in them.
            raise CommandError(error.detail) from error

        self.stdout.write(f"staff    {granted.email}")
        self.stdout.write(
            self.style.WARNING(
                "They sign in at the one door and reach /admin/ from there — there is "
                "no password of ours to set."
            )
        )
