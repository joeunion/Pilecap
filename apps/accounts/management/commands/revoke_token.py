"""`manage.py revoke_token` — the other half of the shell token door.

    uv run python manage.py revoke_token --user you@example.com --name laptop
    uv run python manage.py revoke_token --id 0198f0c2-....-....-............

`issue_token` mints from a shell and has since 2026-08-19. Nothing revoked from
one. The REST door revokes (`DELETE /api/v1/tokens/{token_id}/`) and is
deliberately **self-only**: it takes the token off *your own* list, resolved
from *your* session or *your* bearer. That is the right scope for a route a
person calls about their own laptop, and it is no use at all for the case that
actually happens — an operator minted a token from a shell weeks ago, the
plaintext is gone, nobody holds a session as that user, and the row is still
live. There was no door. This is it.

**It writes nothing itself** (house rule 10). The resolution below is a read;
the single write is `services.revoke_token`, the same service the REST route
calls, so the two doors cannot come to mean different things by "revoked" —
including the socket kick the service does on commit (ADR realtime-2 d), which
an operator revoking a leaked credential wants and would not get from a hand
`UPDATE`.

**Every refusal says why, out loud, and exits non-zero.** That is not a style
note: a door whose refusal path prints nothing and exits
0 reads to a script — and to a person in a hurry — exactly like a success, and
the operator walks away believing a live credential is dead. Every path out of
`handle` below is either a printed revocation or a `CommandError` naming the
reason; there is no third one, and the tests pin each.

**Two ways to name a token, and both are exact.**

`--id` is the one to prefer when a
row's identity matters: it names one row and cannot mean anything else.

`--user` + `--name` is the one a human has. It is exact too — `ApiToken` carries
`UniqueConstraint(fields=["user", "name"])`, so the pair addresses at most one
row, live or revoked, and this command cannot be ambiguous about which token it
found. (The criteria anticipated an ambiguity refusal listing candidates; the
constraint means that state cannot exist. `test_revoke_token_command.py` pins
the constraint rather than the unreachable branch.) What a human actually
mistypes is the *name*, so the miss lists what the person does have.

`--email` is accepted as a second spelling of `--user`, because the mint door
spells it `--email` and an operator pairing the two commands in one runbook
should not have to remember which is which.

**`--tenant` is a confirmation, not an address.** The pair above already found
the row; passing `--tenant` says which workspace you *believe* it is pinned to,
and a disagreement is refused with both values named rather than revoked. It is
the guard for the case this command exists for: several similarly named
machine tokens, and an operator reading a list they did not write.

**Already revoked is a refusal, and that is load-bearing.** The command
addresses only rows with `revoked_at IS NULL`. The bare service overwrites
`revoked_at` with `timezone.now()` unconditionally, so a second run through it
would quietly move the recorded moment of a revocation that happened last
Tuesday — an audit fact edited by a no-op. The filter here is what protects it.
That is a wart in the service, noted and deliberately not fixed here
(the REST door reaches it too); the door refuses instead.

**What this leaves behind.** `revoked_at` on the row; an `AuditEntry` with
`action=accounts.revoke_token` and `door="shell"`, filed under the tenant the
*token* is pinned to (ADR core-22 — the credential's death beside its birth,
and `core.management.BaseCommand`'s bound context is where the door comes
from), recording `kind=system` and no person, which is ADR core-22's absence
(iv) and not a gap: ssh owns who held the shell; and the
`accounts.revoke_token.called` structured line the `@service` wrapper writes.
TOKENS-1 shipped before that ADR and this docstring said the audit row did not
exist, which was true of the tree it was written against and is the class of
sentence that goes stale silently — it is corrected here rather than left to be
believed.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.management.base import CommandError

from apps.accounts.models import ApiToken, User
from apps.accounts.services import revoke_token
from apps.core.actor import system_actor
from apps.core.management import BaseCommand
from apps.core.models import Tenant

#: What the `tenant:` line says for a token pinned to no workspace. The same
#: words `issue_token` prints for the same state, so the two doors describe one
#: row identically.
UNPINNED = "(per request)"


class Command(BaseCommand):
    help = "Revoke an API token, by id or by user and name."

    def add_arguments(self, parser: Any) -> None:
        # No `mutually_exclusive_group`, and no `required=`, for the reason
        # `issue_token` gives about `--scope`: argparse's complaint is a second
        # sentence about the same mistake, phrased by argparse. The checks in
        # `handle` own every refusal this command can give, so all of them read
        # in one voice.
        parser.add_argument(
            "--id",
            dest="token_id",
            default=None,
            help="The token's id. Names one row and cannot mean another.",
        )
        parser.add_argument(
            "--user",
            "--email",
            dest="user",
            default=None,
            help="Email of the person the token acts as. Use with --name.",
        )
        parser.add_argument(
            "--name",
            default=None,
            help="The token's name, exactly as it was minted. Use with --user.",
        )
        parser.add_argument(
            "--tenant",
            default=None,
            help=(
                "Slug of the tenant you believe the token is pinned to. A "
                "disagreement is refused; the token is not addressed by this."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        token = self._resolve(options)
        self._confirm_tenant(token, options["tenant"])
        if token.revoked_at is not None:
            # Refused here, and a silent no-op one layer down. The two
            # are not in tension: the service is reachable from a retrying
            # `DELETE` and owes that door idempotence, while a person at a shell
            # asked a question and deserves an answer — and a script's exit
            # status is not an HTTP contract. What both layers protect is the
            # same fact: `revoked_at` is a record of when something happened,
            # and nothing may move it.
            raise CommandError(
                f"Token {token.pk} ({token.name!r}) was already revoked at "
                f"{token.revoked_at.isoformat()}. Nothing was changed."
            )

        # `token.tenant` — the credential's own pin decides which audit
        # population the revocation joins (ADR core-22). `--tenant` above is a
        # confirmation the operator typed; it is never what gets passed here,
        # so a mismatch is refused before this line rather than filed.
        #
        # `system_actor(tenant=…)` — the shell door's actor, threaded rather
        # than defaulted (ADR core-22, absence iv). The row is honestly
        # `kind=system, actor_user` None: ssh owns who held the shell. What the
        # row DOES owe — the door and the tenant acted on — is said here.
        revoked = revoke_token(
            token=token, tenant=token.tenant, actor=system_actor(tenant=token.tenant)
        )
        moment = revoked.revoked_at
        if moment is None:  # pragma: no cover - the service sets it or raises
            raise CommandError(
                f"Token {revoked.pk} was not recorded as revoked. Nothing can be "
                "claimed about it; check the row before relying on this."
            )

        self.stdout.write(f"revoked:    {revoked.pk}")
        self.stdout.write(f"name:       {revoked.name}")
        self.stdout.write(f"user:       {revoked.user.email}")
        self.stdout.write(f"tenant:     {self._tenant_label(revoked)}")
        self.stdout.write(f"revoked at: {moment.isoformat()}")

    # --- resolution ----------------------------------------------------------

    def _resolve(self, options: dict[str, Any]) -> ApiToken:
        """The one row this invocation named, or a `CommandError` saying why not.

        Both addressing forms are exact (see the module docstring), so this
        returns a row or raises; it never picks one of several.
        """
        token_id = options["token_id"]
        user = options["user"]
        name = options["name"]

        if token_id is not None and (user is not None or name is not None):
            raise CommandError("--id names a token on its own. Drop --user/--name, or drop --id.")
        if token_id is not None:
            return self._by_id(str(token_id).strip())
        if user is not None and name is not None:
            return self._by_user_and_name(str(user).strip().lower(), str(name).strip())
        if user is not None or name is not None:
            missing = "--name" if name is None else "--user"
            raise CommandError(
                f"{missing} is missing. Name a token as --user <email> --name "
                "<name>, or as --id <uuid>."
            )
        raise CommandError(
            "Name the token to revoke: --user <email> --name <name>, or --id <uuid>."
        )

    def _by_id(self, raw: str) -> ApiToken:
        try:
            token_id = UUID(raw)
        except ValueError as bad:
            # Said here rather than by an argparse `type=`, so that `--id
            # nonsense` and `--id <a real uuid nobody has>` read as two
            # sentences from the same door instead of one from argparse and one
            # from us.
            raise CommandError(f"{raw!r} is not a token id.") from bad
        token = ApiToken.objects.filter(pk=token_id).select_related("user", "tenant").first()
        if token is None:
            raise CommandError(f"No token with id {token_id}.")
        return token

    def _by_user_and_name(self, email: str, name: str) -> ApiToken:
        user = User.objects.filter(email=email).first()
        if user is None:
            raise CommandError(f"No user with email {email}.")
        token = (
            ApiToken.objects.filter(user=user, name=name).select_related("user", "tenant").first()
        )
        if token is None:
            raise CommandError(f"{email} has no token named {name!r}. {self._catalogue(user)}")
        return token

    @staticmethod
    def _catalogue(user: User) -> str:
        """What this person *does* have, so a mistyped name is one run to fix.

        The miss is nearly always a name read off somebody else's notes, and a
        refusal that says only "no" sends the operator to the admin or to `psql`
        — which is where a hand `UPDATE` gets typed.
        """
        live = sorted(
            ApiToken.objects.filter(user=user, revoked_at__isnull=True).values_list(
                "name", flat=True
            )
        )
        if not live:
            return "They hold no live tokens."
        return f"Live tokens: {', '.join(repr(one) for one in live)}."

    # --- the confirmation ----------------------------------------------------

    def _confirm_tenant(self, token: ApiToken, slug: Any) -> None:
        if not slug:
            return
        asked = str(slug).strip().lower()
        if not Tenant.objects.filter(slug=asked).exists():
            raise CommandError(f"No tenant with slug {asked}.")
        if self._tenant_label(token) != asked:
            raise CommandError(
                f"Token {token.pk} ({token.name!r}) is pinned to "
                f"{self._tenant_label(token)}, not {asked}. Nothing was revoked."
            )

    @staticmethod
    def _tenant_label(token: ApiToken) -> str:
        tenant = token.tenant
        return tenant.slug if tenant is not None else UNPINNED
