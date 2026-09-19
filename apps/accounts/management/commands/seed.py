"""`manage.py seed` — enough data to sign in and drive the product.

    uv run python manage.py seed

A fresh clone has an empty database, and an empty database with tenancy on is a
product where **every door correctly returns nothing**. That is right, and it is
also a terrible first five minutes: there is no way to tell "the tenancy is
working" from "the API is broken" without a tenant, a person and a membership.
This makes those.

What it makes: one tenant, an owner, a plain member, and an API token printed
once — the smallest set that lets somebody exercise the human door and the
machine door and see the difference between an owner and a member.

**Everything goes through services.** A command is a door (house rule 10), so
it gets the same validation, the same authorization, the same audit rows and
the same `door="shell"` as any other caller. Nothing here calls `.create()`.

**Idempotent.** Run it twice and you get the same tenant and the same people,
plus a second token — because a token's plaintext is shown once and never
again, so "run seed again" is also how you get a new one.

**It refuses to run outside DEBUG without `--force`.** These are published
passwords in a file people copy. A seeded `owner@example.com` on an internet-
facing deployment is not test data, it is an account.

Where it stops: this command seeds the *identity* layer — tenants, people,
memberships, tokens — and nothing product-shaped. It cannot: `accounts` sits
below the domain apps and must not import sideways into them. A product extends
seeding in its own app, with its own command or its own `--` flag, and that is
the intended shape rather than a gap here.

It lives in `accounts` rather than `core` for the same reason: seeding needs a
`User`, `core` is below `accounts`, and `core` imports nothing above it.
"""

from __future__ import annotations

import secrets
from typing import Any

from django.conf import settings
from django.core.management.base import CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import create_user, issue_token
from apps.core.actor import system_actor
from apps.core.authz import OWNER_ROLE, default_role_key
from apps.core.management import BaseCommand
from apps.core.models import Membership, Tenant
from apps.core.services import add_membership, create_tenant

# Published here and therefore worth nothing, exactly like the keys in
# `.env.example`. `--force` and the DEBUG check are what keep them on a laptop.
SEED_PASSWORD = "seeded-development-password"  # pragma: allowlist secret
SEED_TENANT_NAME = "Acme"
SEED_TENANT_SLUG = "acme"
SEED_OWNER_EMAIL = "owner@example.com"
SEED_MEMBER_EMAIL = "member@example.com"


class Command(BaseCommand):
    help = "Create a tenant, an owner, a member and a token, so a fresh clone is drivable."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Seed even with DEBUG off. These are published credentials; mean it.",
        )
        parser.add_argument(
            "--tenant",
            default=SEED_TENANT_SLUG,
            help=f"Slug of the tenant to seed (default: {SEED_TENANT_SLUG}).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "DEBUG is off, so this looks like a real deployment. `seed` creates "
                "accounts whose passwords are published in this repository. Pass "
                "--force if you are certain this is a throwaway environment."
            )

        slug = str(options["tenant"]).strip().lower()
        tenant = Tenant.objects.filter(slug=slug).first()
        if tenant is None:
            name = SEED_TENANT_NAME if slug == SEED_TENANT_SLUG else slug
            tenant = create_tenant(name=name, slug=slug, actor=system_actor())
            self.stdout.write(f"created tenant  {tenant.slug}")
        else:
            self.stdout.write(f"tenant exists   {tenant.slug}")

        # The two roles by KEY, not by enum member: `owner` is the reserved
        # platform role (`core.authz.OWNER_ROLE`) and the second person gets
        # whatever this deployment declares a new member to be — which is
        # `member` on the template and whatever `roles.py` says in a product
        # that renamed it. A seed that spelled the enum would seed a role a
        # product may not declare.
        owner = self._person(email=SEED_OWNER_EMAIL, tenant=tenant, role=OWNER_ROLE)
        self._person(email=SEED_MEMBER_EMAIL, tenant=tenant, role=default_role_key())

        # A token's name is unique per user, so the name carries the run: a
        # second `seed` mints a second token rather than colliding with the
        # first — which is the whole reason re-running is how you get one. The
        # date keeps the list readable; the random tail is what makes two runs
        # in the same second two tokens rather than an `Invalid`.
        stamp = f"{timezone.now():%Y%m%d}-{secrets.token_hex(3)}"
        # No ceiling, said out loud rather than left to a default (ADR ident-7).
        # This is a development convenience whose whole job is to let somebody
        # try every door in one sitting, so a narrow token would be the wrong
        # answer — but "wide because nobody chose" and "wide because this is
        # what it is for" look identical in a diff, and only one of them is a
        # decision.
        _token, plaintext = issue_token(
            user=owner,
            tenant=tenant,
            name=f"seed-{tenant.slug}-{stamp}",
            # The shell door's actor (ADR core-22, absence iv), like every
            # other command: `seed` is the deployment setting itself up, and
            # attributing that to the demo owner it just created would be the
            # fiction `system_actor`'s docstring warns about.
            actor=system_actor(tenant=tenant),
            scopes=["*"],
        )

        self.stdout.write("")
        self.stdout.write(f"  sign in as   {SEED_OWNER_EMAIL} / {SEED_PASSWORD}")
        self.stdout.write(f"  or as        {SEED_MEMBER_EMAIL} / {SEED_PASSWORD}")
        self.stdout.write(f"  tenant       {tenant.slug}  (send it as X-Tenant)")
        self.stdout.write("")
        # On its own line, like `issue_token` prints it, so a shell can take the
        # last line and use it without parsing prose.
        self.stdout.write("  bearer token, for Authorization: Bearer ...")
        self.stdout.write(plaintext)
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING("The token is not stored; run seed again for another one.")
        )

    def _person(self, *, email: str, tenant: Tenant, role: str) -> User:
        """A user with a membership of this tenant, made if either is missing."""
        user = User.objects.filter(email=email).first()
        if user is None:
            user = create_user(email=email, password=SEED_PASSWORD)
            self.stdout.write(f"created user    {email}")
        else:
            self.stdout.write(f"user exists     {email}")

        if not Membership.objects.filter(user_id=user.pk, tenant=tenant).exists():
            add_membership(
                user=user,
                tenant=tenant,
                is_default=not Membership.objects.filter(user_id=user.pk).exists(),
                role=role,
                actor=system_actor(tenant=tenant),
            )
            self.stdout.write(f"  joined {tenant.slug} as {role}")
        return user
