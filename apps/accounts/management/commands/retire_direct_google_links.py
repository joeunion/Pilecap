"""`manage.py retire_direct_google_links` — take away the direct Google road's leftovers.

    uv run python manage.py retire_direct_google_links --dry-run
    uv run python manage.py retire_direct_google_links

The last step of a product's move off the retired direct-allauth Google road,
run AFTER a staff sign-in through Zitadel's Google button is proven. Every
person that road created keeps an allauth `SocialAccount(provider="google")`;
with the provider no longer installed each is a row no provider serves — it
signs nobody in, the connections page under `/accounts/3rdparty/` leaves it
out without saying so, and any code that asks it for its provider account
(`get_provider_account()`) gets an error.

A door onto `services.retire_direct_google_links`, which deletes them only when
EVERY holder already carries a Zitadel identity and otherwise refuses, naming
who has not signed in through Zitadel yet.

**Exit status:** 0 done (or, with `--dry-run`, nothing in the way) · 2 refused —
somebody holding a direct-road row has no Zitadel identity yet; the names are
printed and nothing is deleted.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.accounts.selectors import get_direct_google_links
from apps.accounts.services import retire_direct_google_links
from apps.core.actor import actor_for, system_actor
from apps.core.exceptions import DomainError
from apps.core.management import BaseCommand

REFUSED = 2


class Command(BaseCommand):
    help = (
        "Delete the retired direct Google road's SocialAccount rows, once every "
        "holder has a Zitadel identity."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print how many rows would go, and who is still in the way; delete nothing.",
        )
        parser.add_argument(
            "--as",
            dest="acting_email",
            default=None,
            help="Superuser to attribute this to. Omit to act as the system.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["dry_run"]:
            census = get_direct_google_links()
            self.stdout.write(f"would retire  {census.retirable} direct Google link(s)")
            if census.unjoined:
                raise CommandError(
                    "refused      these people have no Zitadel identity yet: "
                    f"{', '.join(census.unjoined)}",
                    returncode=REFUSED,
                )
            return

        email = options["acting_email"]
        if email:
            user = User.objects.filter(email=str(email).strip().lower()).first()
            if user is None:
                raise CommandError(f"No user with email {email}.", returncode=REFUSED)
            actor = actor_for(user=user, tenant=None, kind="human")
        else:
            actor = system_actor(None)

        try:
            removed = retire_direct_google_links(actor=actor, tenant=None)
        except DomainError as error:
            raise CommandError(error.detail, returncode=REFUSED) from error
        self.stdout.write(f"retired      {removed} direct Google link(s)")
