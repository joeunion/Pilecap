"""`manage.py unlink_identity` — cut the join to the identity platform.

    uv run python manage.py unlink_identity --email you@example.com --reason "re-seeded"
    uv run python manage.py unlink_identity --all --yes --reason "issuer swapped"

**The road that makes the sign-in refusal survivable.** A person here is joined
to a subject at the identity platform, and that join is theirs: an assertion
carrying a *different* subject for an account that already holds one is refused,
because taking it would be an account takeover with an extra step. Everything
that legitimately changes subjects — swapping the issuer, re-seeding the
deployment's identity platform, rebuilding one person's account there — changes
them for people who are exactly who they say they are, and without this command
that whole population would be locked out with no way back.

**It writes nothing itself** (house rule 10). The single write is
`services.unlink_zitadel_identity`, which authorizes, clears the column, deletes
the person's platform `SocialAccount` rows, closes their sockets on commit and
leaves the audit row; this command resolves rows and prints. A hand `UPDATE`
would skip all five.

**Why a shell door and not a route.** The persona is the deployment's operator,
at an altitude no tenant holds — the same place `bootstrap_tenant` and
`zitadel_first_admin` live. A route that cut somebody's identity join on request
is the shape the refusal exists to close; ssh is the credential, and the audit
row carries `door="shell"` — the value `core.management.BaseCommand` binds for
every command in this tree — and the reason.

**A person with no subject is a no-op that says so.** Nothing is cut, so nothing
is called: no audit row about an act that did not happen, and no sockets closed
under somebody whose identity nobody touched. The line printed says `nothing to
unlink`, which is the true answer and not a success report.

**`--reason` is required, and it is the point.** "Every subject changed at once"
and "this one person's platform account was rebuilt" are different acts with the
same effect on the row, and six months later the ledger is the only place that
difference still exists.

**`--all` prints the count before it does anything and refuses without `--yes`.**
The population is everybody holding a subject in the identity join — on a live
deployment that is every person who has ever signed in, and the next thing each
of them does is sign in again. An operator should see that number before it
happens, not after.

**Every refusal exits non-zero and says why.** A door whose refusal path prints
nothing and exits 0 reads to a script, and to a person in a hurry, exactly like
a success — and here that would leave an operator believing a locked-out
deployment had been freed.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import CommandError
from django.db.models import Exists, OuterRef

from apps.accounts.models import SsoIdentity, User
from apps.accounts.services import unlink_zitadel_identity
from apps.core.actor import system_actor
from apps.core.management import BaseCommand


class Command(BaseCommand):
    help = "Cut a person's link to the identity platform so a new subject can be recorded."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--email", help="The one person to unlink, by address.")
        parser.add_argument(
            "--all",
            action="store_true",
            help="Every person holding a subject. Needs --yes.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Confirm a --all run after reading the count it prints.",
        )
        parser.add_argument(
            "--reason",
            required=True,
            help="Why, in words. It rides every audit row this run writes.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        email = options.get("email")
        every = bool(options.get("all"))
        reason = str(options.get("reason") or "").strip()

        if not reason:
            raise CommandError("--reason cannot be empty: the audit row carries it.")
        if every and email:
            raise CommandError("--all unlinks everybody. Drop --email, or drop --all.")
        if not every and not email:
            raise CommandError("Name somebody with --email, or say --all.")

        actor = system_actor(tenant=None)

        if every:
            # An EXISTS, never a join filter: `connection__isnull` across the
            # reverse relation also matches a person with no row at all.
            joined = SsoIdentity.objects.filter(user=OuterRef("pk"), connection__isnull=True)
            people = list(User.objects.filter(Exists(joined)).order_by("email"))
            # THE COUNT FIRST, ALWAYS — printed whether or not `--yes` was
            # passed, because the refusal is only useful if it tells the
            # operator what they were about to do.
            self.stdout.write(f"people holding a subject: {len(people)}")
            if not options.get("yes"):
                raise CommandError(
                    "That would unlink every one of them and each has to sign in again. "
                    "Re-run with --yes if that is what you mean."
                )
            for person in people:
                unlink_zitadel_identity(user=person, actor=actor, tenant=None, reason=reason)
                self.stdout.write(f"unlinked: {person.email}")
            self.stdout.write(f"unlinked {len(people)} person(s)")
            return

        target = User.objects.filter(email=str(email).strip().lower()).first()
        if target is None:
            # COULD NOT LOOK, not "nothing to do": an operator who mistyped an
            # address and read a success would believe a person was freed. Exit
            # **2**, the tree's could-not-do status (`newapp.py`'s `_refuse`) —
            # a mistyped address and a person who was found and left alone are
            # different answers, and 1 says "refused", not "I never looked".
            raise CommandError(f"No account here has the address {email}.", returncode=2)
        if not target.sso_identities.filter(connection__isnull=True).exists():
            # NOT a refusal and not an act: the join is already cut. Calling the
            # service would file an audit row about an unlink that did not
            # happen and close the sockets of somebody nobody touched.
            self.stdout.write(f"nothing to unlink: {target.email} holds no subject")
            return
        unlink_zitadel_identity(user=target, actor=actor, tenant=None, reason=reason)
        self.stdout.write(f"unlinked: {target.email}")
