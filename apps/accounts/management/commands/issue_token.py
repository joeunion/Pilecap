"""`manage.py issue_token` — the token door for someone with a shell.

    uv run python manage.py issue_token --email you@example.com --tenant acme \
        --name laptop --scope widgets:read --scope widgets:write

Prints the plaintext once, on stdout, and nothing else prints it ever again:
only the SHA-256 is stored. It is the same operation `POST /api/tokens/`
performs, through the same service — the two doors cannot drift.

`--tenant` is optional. With it, the token is pinned to that tenant and acts
nowhere else. Without it, the token resolves its tenant exactly as a signed-in
request does, from the user's default membership.

`--scope` is NOT optional, and it is the same contract the HTTP door has: a
token handed to somebody else's software should be as narrow as the job needs,
and a default would quietly make it as wide as the person. Repeat the flag once
per scope, or pass `--scope '*'` to say out loud that this one should have no
limit. The refusal for a missing, empty or unknown scope is the shared one both
doors raise, printed as this command's own error, so the browser and the shell
cannot come to say two different things about one mistake.

**Two lines about reach, and they answer different questions.** `scopes:`
is what the row stores — exactly what was asked for. `effective:` is what the
token can actually do, which is the same `effective_scopes` the HTTP mint echoes
back: within a section the write scope carries the read, so `--scope
widgets:write` mints a token whose effective set is `widgets:read,
widgets:write`. An operator minting for an agent reads the second line and knows
what they handed over; previously the expansion existed only on the wire,
and the shell — the door somebody with a machine to set up actually uses — never
mentioned it.

`note:` is the third, and it appears only when something is **wrong**: a scope
was asked for that this person's role cannot back, so the token carries it and
every call needing it is refused underneath anyway. It keys on that set and on
nothing else. It used to key on "effective differs from asked-for", which is
true of every ordinary `:write` mint by design, and so printed a warning naming
an empty list on a mint with nothing at all wrong with it.

**And both of those lines need a tenant to have an answer at all.**
`effective:` is worked out from the role this person holds *in the token's
tenant*, so a mint with no `--tenant` has nothing to work it out against —
the tenant of an unpinned token is resolved per request, at the door, from
whichever membership the request lands on. Asking anyway got the empty set
back, which is an answer about what the mint does not know dressed as an
answer about what the person cannot do: **every** unpinned mint printed
"(nothing this role can back today)" and a `note:` naming every scope asked
for, on a token that then worked perfectly. So when no tenant was named the
two lines say where the answer actually comes from and there is nothing to
warn about; with `--tenant` both are computed exactly as before.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import system_actor
from apps.core.api.scopes import ceiling_from_request, effective_scopes
from apps.core.exceptions import Invalid
from apps.core.management import BaseCommand
from apps.core.models import Membership, Tenant

#: What the `effective:` line says when no `--tenant` was named and the token
#: carries a ceiling. Not a set, and deliberately not an empty one: the reach is
#: real and it is worked out at the door, against the membership the request
#: lands on. It echoes the `(per request)` the `tenant:` line above it already
#: prints, so the two lines read as one fact rather than two.
PER_REQUEST = "(per request — resolved at the door)"


class Command(BaseCommand):
    help = "Mint an API token for a user, and print the plaintext once."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--email", required=True, help="The user the token acts as.")
        parser.add_argument("--name", required=True, help="How you will recognise it later.")
        parser.add_argument(
            "--tenant",
            default=None,
            help="Tenant slug to pin the token to. Omit to resolve per request.",
        )
        # No `required=True`: argparse's own complaint would be a second
        # sentence about the same mistake, and it would be the one the shell
        # sees while the browser sees the other. The shared check below owns
        # both, so `--scope` missing here reads exactly as `scopes` missing
        # over the wire.
        parser.add_argument(
            "--scope",
            action="append",
            default=None,
            dest="scopes",
            help=(
                "A scope this token may use, as section:read or section:write. "
                "Repeat once per scope. Required; pass '*' for no limit."
            ),
        )

    @staticmethod
    def _effective_line(usable: list[str] | None) -> str:
        """What the `effective:` line says, for each of the three real answers.

        `None` is a token minted `*`: it asked for nothing in particular, so
        there is nothing to expand or to trim, and the line says the same thing
        the `scopes:` line above it says rather than going quiet — a missing
        line reads as "we did not work it out", which is not what happened.

        Empty is the honest and alarming answer: this person's role backs none
        of what was asked for, so the token will be refused underneath on every
        call. The `note:` below names which scopes; this line is why the list is
        empty rather than short.

        That branch is only reached on a mint that named a tenant —
        an unpinned mint has no role to ask about and says so with `PER_REQUEST`
        rather than computing a set — and `handle` has already refused a
        `--tenant` this person holds no membership in, so rank zero is now a
        race (a membership dropped between that check and this call) rather than
        the ordinary case it used to be. It stays because this helper's contract
        is every answer `effective_scopes` can give, and because an empty list
        printed as nothing at all would be the same class of silence this guards against.
        """
        if usable is None:
            return "(no limit)"
        return ", ".join(usable) if usable else "(nothing this role can back today)"

    def handle(self, *args: Any, **options: Any) -> None:
        email = str(options["email"]).strip().lower()
        user = User.objects.filter(email=email).first()
        if user is None:
            raise CommandError(f"No user with email {email}.")

        tenant: Tenant | None = None
        slug = options["tenant"]
        if slug:
            tenant = Tenant.objects.filter(slug=str(slug).strip().lower()).first()
            if tenant is None:
                raise CommandError(f"No tenant with slug {slug}.")
            if not Membership.objects.filter(user=user, tenant=tenant).exists():
                raise CommandError(f"{email} is not a member of {tenant.slug}.")

        try:
            ceiling = ceiling_from_request(options["scopes"])
        except Invalid as refusal:
            # The shell door's own vocabulary for a refusal the service layer
            # raised, exactly as `config/api.py` turns the same refusal into a
            # status code for the HTTP door. The sentence is the registry's;
            # only the wrapper is this door's.
            raise CommandError(str(refusal)) from refusal

        token, plaintext = issue_token(
            user=user,
            tenant=tenant,
            name=str(options["name"]),
            # The shell door's actor, threaded explicitly rather than left to
            # the bound context (ADR core-22, absence iv). `kind=system` and
            # `actor_user` None is the HONEST row for a command: the box's own
            # access audit owns who held the shell, and this table does not
            # duplicate an authority it cannot verify. Naming `--email`'s person
            # as the actor would be the fiction the ADR names — that person is
            # who the credential is FOR, not who minted it.
            actor=system_actor(tenant=tenant),
            scopes=ceiling,
        )

        self.stdout.write(f"token id:  {token.pk}")
        self.stdout.write(f"user:      {user.email}")
        self.stdout.write(f"tenant:    {tenant.slug if tenant is not None else '(per request)'}")
        self.stdout.write(f"scopes:    {', '.join(token.scopes) if token.scopes else '(no limit)'}")
        if token.scopes is not None and tenant is None:
            # The mint was not told which tenant to ask about, so there is
            # no role here to work a set out against — the tenant of an unpinned
            # token is resolved per request, at the door, from the membership the
            # request lands on. `effective_scopes` handed a `None` tenant finds
            # no membership, ranks zero and returns the EMPTY SET, which is an
            # answer about this command's ignorance wearing the shape of an
            # answer about the person: an owner of `acme` minting `usage:read`
            # unpinned was told their role backs nothing, and then the token
            # resolved `acme` at the door with `usage:read` live on it. So the
            # line says where the answer comes from and no note is computed —
            # there is no dead scope to name, because nothing was asked.
            #
            # `--scope '*'` is outside this branch on purpose: a token with no
            # ceiling has nothing to expand or to trim, so "(no limit)" is the
            # whole truth whether a tenant was named or not, and that line reads
            # identically in both modes.
            self.stdout.write(f"effective: {PER_REQUEST}")
        else:
            # N184b: the same echo the HTTP door returns, at the door an operator
            # actually mints from. `effective_scopes` is where `widgets:write`
            # becomes `widgets:read, widgets:write` — asking for the write half
            # carries the read half — and somebody setting an agent up should
            # read what the token can do rather than work it out from a rule they
            # have to know. The wire has said it since ADR ident-7; the shell had
            # not.
            usable = effective_scopes(user=user, tenant=tenant, scopes=token.scopes)
            self.stdout.write(f"effective: {self._effective_line(usable)}")
            # N184a: the note is about scopes that are DEAD — asked for, and not
            # backed by this person's role — and `dead` is the only thing that
            # says so. It used to key on `set(usable) != set(token.scopes)`,
            # which is a different question and answers yes on every ordinary
            # `:write` mint, because the effective set legitimately GAINS the
            # family's read. The sentence then named an empty list: "role cannot
            # back  today" (FT-1′ F1). A warning that fires when nothing is wrong
            # is a warning nobody reads the day something is.
            asked = set(token.scopes or ())
            dead = sorted(asked - set(usable)) if asked and usable is not None else []
            if dead:
                self.stdout.write(
                    self.style.WARNING(
                        f"note:      {user.email}'s role cannot back {', '.join(dead)} today, "
                        "so calls needing those will be refused underneath anyway."
                    )
                )
        self.stdout.write("")
        self.stdout.write(plaintext)
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING("Copy it now. It is not stored and cannot be shown again.")
        )
