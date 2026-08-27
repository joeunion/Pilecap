"""`manage.py bootstrap_tenant` — make the first tenant of an installation.

    uv run python manage.py bootstrap_tenant --email you@yourcompany.com

Every deployment has to do this once, and until now nothing wrote it down: the
seed command is development data and refuses outside DEBUG, so a real
environment's first tenant was made by hand-driving services in a shell.

It makes three rows in one transaction — the tenant, its root organization, and
one owner membership for the person you name — and it refuses if the
installation already has a tenant, so running it twice is a refusal rather than
a surprise.

The person must already exist. On a real environment they do: they signed in
through your identity provider, which is what created their record. Naming
somebody who has not is refused rather than guessed at.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.utils.text import slugify

from apps.core.exceptions import DomainError
from apps.core.management import BaseCommand
from apps.core.models import Membership, Organization
from apps.core.services import create_first_tenant


class Command(BaseCommand):
    help = "Create the first tenant, its root organization, and its first owner."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--email",
            required=True,
            help="The person who will own this tenant. They must already have signed in once.",
        )
        parser.add_argument(
            "--name",
            default=None,
            help="What to call the tenant. Defaults to the part of the email after the @.",
        )
        parser.add_argument(
            "--slug",
            default=None,
            help="The tenant's handle in URLs and headers. Defaults to a slug of the name.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        email = str(options["email"]).strip().lower()
        user = get_user_model().objects.filter(email=email).first()
        if user is None:
            raise CommandError(
                f"There is no account for {email}.\n"
                "Whoever will own this tenant has to sign in once first — that is what "
                "creates their record. Open /accounts/login/, sign in through the "
                "identity provider, and run this again.\n"
                "Not `manage.py seed`: that makes a person AND a tenant, and this "
                "command refuses to run once any tenant exists — so seeding to satisfy "
                "this message would destroy the precondition for the next line of it."
            )

        name = str(options["name"] or email.split("@")[-1].split(".")[0]).strip()
        slug = str(options["slug"] or slugify(name)).strip().lower()

        try:
            tenant = create_first_tenant(user=user, name=name, slug=slug)
        except DomainError as refusal:
            # The refusal already says what is true; a command that reworded it
            # would be a second copy of the sentence, and the two would drift.
            raise CommandError(str(refusal.detail)) from refusal

        root = Organization.objects.for_tenant(tenant).get(parent__isnull=True)
        membership = Membership.objects.get(user=user, tenant=tenant)

        self.stdout.write("Created the first tenant of this installation.")
        self.stdout.write("")
        self.stdout.write(f"  tenant        {tenant.name}  (slug: {tenant.slug})")
        self.stdout.write(f"  organization  {root.name}  (slug: {root.slug})")
        self.stdout.write(f"  owner         {email}  (role: {membership.role})")
        self.stdout.write("")
        self.stdout.write(
            "Check the name and the address above. If either is wrong, the fix is to "
            "start again from an empty database — this command will refuse to run twice."
        )
        self.stdout.write(
            self.style.SUCCESS(f"Sign in as {email} and you will land in {tenant.slug}.")
        )
