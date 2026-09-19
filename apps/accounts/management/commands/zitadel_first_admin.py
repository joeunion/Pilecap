"""`manage.py zitadel_first_admin` — the deployment's first human, once.

    uv run python manage.py zitadel_first_admin --email you@yourcompany.com

**The door that was missing.** With self-registration closed (ADR ident-8) a
deployment that does not federate has no way to its first identity but Zitadel's
own console or its `FirstInstance` admin: `bootstrap_tenant` needs a `User` row,
a `User` row is minted by a first sign-in, and a first sign-in needs an account
somebody has to have made. That circle was measured from zero on a sibling
product at twenty-one minutes with a console in the loop, and every step of it
was somebody reading Zitadel's admin UI rather than this product's.

**What it does, all of it through the existing writers.** It makes a
credential-less Zitadel human, mints an invitation code, and prints the hosted
link where that person sets their own password — then the two steps after it, in
order, as sentences an operator follows. It writes **no row of ours** and no
audit entry, because nothing of ours changed: the birth certificate is
`bootstrap_tenant`'s audited write (ADR core-17), and it comes last.

**We never see, choose or transport a password.** `ensure_invited_user` takes
none and `create_invite_code` returns a code the invited person exchanges for
credentials they pick — which is what makes this different in kind from making
an account with a password we mail somebody. The code is printed to the
operator's terminal once and is in no log line, no row and no email
(`returnCode`, never `sendCode`: the product has exactly one sender and Zitadel
is not it).

**It refuses the moment there is a tenant**, before it dials anything. From the
first member on, the product's own invitation door is the only one:
`core.services.invite_member` through REST and MCP, which writes a row, audits
it, and provisions the identity in a workflow that retries. A second invitation
path standing beside it is a second way for somebody to arrive that nothing
audits — so this one is a door to day zero and not an operator's convenience,
and there is deliberately no `--force`.

**A deployment that federates at birth never runs this.** Its first human signs
in through the workforce IdP, the adapter mints the `User`, and
`bootstrap_tenant` follows. ADR ident-9 records both doors, and names deleting
this command as the reversal for a product that only ever needs the other one.

**It is a door** (house rule 10) so it reaches Zitadel through
`apps.accounts.zitadel` like the seed and the activity do, and house rule 27's
allow-list names this file with that reason.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import CommandError
from django.urls import reverse

from apps.accounts import zitadel

# The naming rule an invited person gets, shared with the invitation workflow's
# activity rather than copied: a second copy would drift, and what a person is
# called on the screen where they set their password should not depend on which
# door invited them. It is private to `apps.accounts` and this is `apps.accounts`.
from apps.accounts.activities import _invited_person_names
from apps.core.management import BaseCommand
from apps.core.models import Tenant

# Deliberately loose. This is not an address validator — nothing here can know
# whether a mailbox exists — it is a typo catch, so that `--email alice` becomes
# a refusal on this side rather than a Zitadel account named `alice` that
# nobody can ever reach. The real proof is the person opening the link.
EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")

# Hosts that mean "this machine". A `PUBLIC_BASE_URL` on one of these is right
# on a laptop and a lie anywhere else: the two steps this command prints are
# addresses the invited person has to open, and an address that only resolves
# on the server is a dead end printed with confidence. The production settings
# module does not yet refuse a loopback PUBLIC_BASE_URL (a standing SHOULD in
# the ledger since 2026-08-31), so this door carries its own.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


class Command(BaseCommand):
    help = "Invite this deployment's first human, before any tenant exists."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--email",
            required=True,
            help=(
                "The address of the person who will own this installation. They set "
                "their own password through the link this prints."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        email = str(options["email"]).strip().lower()
        self._refuse_unless_ready(email=email)

        first_name, last_name = _invited_person_names(email)
        user = zitadel.ensure_invited_user(email=email, first_name=first_name, last_name=last_name)
        try:
            code = zitadel.create_invite_code(user_id=user.id)
        except zitadel.ZitadelError as error:
            if not zitadel.is_already_initialized(error):
                # Anything else is the platform failing, and the message Zitadel
                # sent is the useful half — the same handling `zitadel_seed` gives it.
                raise CommandError(str(error)) from error
            raise CommandError(self._already_initialized(email)) from error

        if not user.created:
            # Not a warning about this run — a fact about the previous one. A
            # code is single-use and Zitadel supersedes rather than reissues
            # (`create_invite_code`'s docstring records that as measured), so an
            # operator who sent the first link somewhere must know it is dead.
            self.stdout.write(
                self.style.WARNING(
                    f"{email} already had an account here, so a previous code for {email} "
                    "is now void. Send the link below, not an older one."
                )
            )

        self._say_what_happens_next(email=email, url=zitadel.invite_url(user_id=user.id, code=code))

    # --- the refusals --------------------------------------------------------

    def _refuse_unless_ready(self, *, email: str) -> None:
        """Every reason not to start, checked before anything is dialled.

        Order matters in exactly one place and it is the first check: **the
        tenant check runs before any Zitadel call**, so a deployment that is
        past day zero cannot have an account made for it by a command it was
        going to be refused by anyway. The rest are ordered cheapest first.
        """
        if not EMAIL_SHAPE.match(email):
            raise CommandError(
                f"{email!r} is not an email address. This command invites a person by "
                "address; the address is the account's username and the inbox the link "
                "goes to."
            )

        existing = Tenant.objects.first()
        if existing is not None:
            raise CommandError(
                f"This installation already has a tenant ({existing.slug}), so it already "
                "has a first human and this door is shut.\n"
                "Invite the next person through the product instead: POST "
                "/api/v1/memberships/invitations/ or the MCP tool beside it, both of "
                "which write an invitation row, audit it, and provision the identity in "
                "a workflow that retries. That is the one invitation path from the first "
                "member on, and there is no flag here that reopens this one."
            )

        if not zitadel.configured():
            raise CommandError(
                "Zitadel is not configured: ZITADEL_ISSUER and ZITADEL_PAT must both be "
                "set. ./scripts/setup.sh writes the PAT into .env from the "
                "zitadel_bootstrap volume; if that volume is gone, reset the instance "
                "(drop the zitadel database and the volume) and run setup again."
            )

        base = str(getattr(settings, "PUBLIC_BASE_URL", "")).rstrip("/")
        if not settings.DEBUG and (urlsplit(base).hostname or "") in LOOPBACK_HOSTS:
            raise CommandError(
                f"PUBLIC_BASE_URL is {base!r}, which only resolves on this machine, and "
                "DEBUG is off.\n"
                "Two of the three steps this command prints are addresses the invited "
                "person opens in their own browser, so printing them from a loopback "
                "base URL would be printing a dead end with confidence. Set "
                "PUBLIC_BASE_URL to the address this deployment is actually reached at "
                "and run this again."
            )

    @staticmethod
    def _already_initialized(email: str) -> str:
        """Zitadel's `ALREADY_INITIALIZED`, turned into the next thing to do.

        Not a failure and not retried: this person set credentials already, so
        there is nothing to invite them to set. What is left of the day-zero
        walk is the two steps after the link, and they are still true — so the
        refusal is the remainder of the runbook rather than a report of an
        error id.
        """
        base = str(getattr(settings, "PUBLIC_BASE_URL", "")).rstrip("/")
        return (
            f"{email} already has credentials at this identity platform, so there is "
            "nothing to invite them to set.\n"
            f"Sign in at {base}{reverse('account_login')} as {email} — that first sign-in "
            "is what mints their record here — then run:\n"
            f"    uv run python manage.py bootstrap_tenant --email {email}"
        )

    # --- the output ----------------------------------------------------------

    def _say_what_happens_next(self, *, email: str, url: str) -> None:
        """The link once, then the three steps, in the order they are done.

        **The link is printed once and stored nowhere** — the precedent is
        `zitadel_seed`'s `--rotate-web-secret`, which prints a client secret the
        same way for the same reason: some values exist for exactly one person
        to act on once, and writing them anywhere else is how they end up in a
        log sink. Re-running mints a new code and voids this one.

        The steps are sentences rather than a bulleted vocabulary because the
        person reading them is doing this for the first time and possibly only
        once.

        **How many steps there are is the DOOR's answer** (A7, design C-11).
        Under `hosted` the landing page is Zitadel's, where it goes after the
        password is set is a measured fact about somebody else's front end
        (WATCH F6: it goes to `/ui/console/`), and a separate sign-in at our
        address is a real act the person has to perform — three steps. Under
        `ours` the invite road sets the password and signs them in on the same
        page-load, so a printed "now go and sign in" would be an instruction
        to do something already done, on a screen they are already past —
        two steps. A command that printed the same three either way would be
        wrong on one of the two doors, and it is the day-zero walk it would be
        wrong on.
        """
        base = str(getattr(settings, "PUBLIC_BASE_URL", "")).rstrip("/")
        login = f"{base}{reverse('account_login')}"

        self.stdout.write("")
        self.stdout.write(f"Invited {email}. They have no credentials yet; this link is how")
        self.stdout.write("they choose their own. Send it to them, or open it yourself:")
        self.stdout.write("")
        self.stdout.write(f"    {url}")
        self.stdout.write("")
        self.stdout.write("Then, in order:")
        self.stdout.write(f"  1. Open the link and set a password. {self._whose_page()}")
        step = 2
        if not self._lands_here():
            self.stdout.write(
                f"  2. Sign in at {login} as {email}. That first sign-in is what creates their "
                "record in this product."
            )
            step = 3
        else:
            self.stdout.write(
                f"     Setting it signs them in here and lands them on {base}, and that first "
                "sign-in is what creates their record in this product."
            )
        self.stdout.write(
            f"  {step}. Run: uv run python manage.py bootstrap_tenant --email {email}\n"
            "     That makes the first tenant, its root organisation and their owner "
            "membership, and it is the audited write this installation starts from."
        )
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "The link is shown once and is not stored anywhere. Re-running this "
                "command mints a new code and voids the one above."
            )
        )

    @staticmethod
    def _whose_page() -> str:
        """Whose front end step one lands on. **The door decides** (A5.5).

        ADR ident-9 said "prints the hosted set-password link" when there was
        one front end; design Decision 3 amends that to "the deployment's
        sign-in door's link", and this sentence is where the amendment is
        visible to the person doing the walk. Saying "the identity platform's,
        not this product's" under `ours` would send the first human of the
        deployment looking for a screen that is not there — and the whole
        reason this command exists is that the twenty-one-minute version of
        day zero was somebody reading a console they had not been told about.
        """
        if Command._lands_here():
            return "The page is this product's own, at the address above."
        return "The page is the identity platform's, not this product's."

    @staticmethod
    def _lands_here() -> bool:
        """Whether this deployment's invite link opens a page of OURS.

        One comparison, read by both sentences above, because the two are one
        fact: a link to our page under a sentence about somebody else's, or a
        count of steps that assumes a sign-in the road already did, are the
        same defect seen from two places.
        """
        return str(getattr(settings, "SIGN_IN_DOOR", "hosted")) == "ours"
