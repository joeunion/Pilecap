"""`manage.py zitadel_brand` — state what this deployment's sign-in screen should look like.

    uv run python manage.py zitadel_brand --accent "#0b7285"

**The shell door onto `set_identity_branding`.** Before this command
the service had exactly one production caller — `apply_identity_config`,
recording the *outcome* of a run — and nothing at all that could ask for one.
This is that: the intent-writing half, the same shape `sync_workforce_idp` is
for `sync_workforce_identity_config`.

**Every field is optional, and omitting one KEEPS what the live row already
says** — this is a restyle, not a replacement, so changing one colour never
silently blanks the other five. On the very first call there is nothing to
keep, and `product_name` / `accent` fall back to `settings.PRODUCT_NAME` /
`settings.BRAND_ACCENT`, the one-declared-value law `set_identity_branding`'s
docstring names. `--disable-watermark` only ever turns the watermark OFF; there
is deliberately no `--enable-watermark`, because a boolean flag with a plain
default cannot tell "leave it as it was" from "turn it back on" and the
row-level default already means "leave it as it was" for every field but this
one is spoken about as an override.

**It writes the intent row and returns immediately.** The management call
happens later, in an activity, on a run started **on commit** (house rule 27):
this command imports no Zitadel client and never could, because it is a door
and a door calls services (house rule 10). Watch the run in Temporal, or read
the result with `manage.py zitadel_audit`, which gained a branding clause the
same rung this command did.

**Who may.** `deployment.configure` — a superuser, not a tenant's owner
(`apps/accounts/policies.py` says why: this is the deployment's own screen, and
an owner of one customer's workspace has no business changing what everybody
signs in through). `--as` names them, so the audit row carries a person rather
than "the shell"; `--tenant` is the same optional audit anchor
`sync_workforce_idp` documents — it decides where the audit row is filed, never
where the run acts.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.accounts.services import set_identity_branding
from apps.core.actor import actor_for, system_actor
from apps.core.exceptions import DomainError
from apps.core.management import BaseCommand
from apps.core.models import Tenant


class Command(BaseCommand):
    help = "State this deployment's hosted sign-in screen branding, and queue it to Zitadel."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--product-name", default="", help="Shown on the hosted screen.")
        parser.add_argument(
            "--accent", default="", help="Zitadel's primaryColor, as a CSS hex string."
        )
        parser.add_argument("--background-color", default="")
        parser.add_argument("--font-color", default="")
        parser.add_argument("--background-color-dark", default="")
        parser.add_argument("--font-color-dark", default="")
        parser.add_argument("--logo-url", default="", help="A URL Zitadel can fetch the logo from.")
        parser.add_argument(
            "--disable-watermark",
            action="store_true",
            default=False,
            help=(
                "Turn the watermark off. There is no --enable-watermark; omitting this "
                "flag keeps whatever the live row already says."
            ),
        )
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
            row = set_identity_branding(
                actor=actor,
                tenant=tenant,
                product_name=str(options["product_name"]),
                accent=str(options["accent"]),
                background_color=str(options["background_color"]),
                font_color=str(options["font_color"]),
                background_color_dark=str(options["background_color_dark"]),
                font_color_dark=str(options["font_color_dark"]),
                logo_url=str(options["logo_url"]),
                is_watermark_disabled=(True if options["disable_watermark"] else None),
            )
        except DomainError as error:
            raise CommandError(error.detail) from error

        self.stdout.write(
            f"set      identity branding  ({row.pk}) "
            f"product_name={row.product_name!r} accent={row.accent}"
        )
        self.stdout.write(
            self.style.WARNING(
                "The run materialises it. Watch it in Temporal, or read the result "
                "with `manage.py zitadel_audit`."
            )
        )
