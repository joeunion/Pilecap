"""`manage.py zitadel_seed` — the identity objects a fresh clone needs.

    uv run python manage.py zitadel_seed

Zitadel starts with an organisation, an admin and a machine user, and nothing a
product can sign anybody in *through*. This makes the rest: the project every
application hangs off, the browser RP client W2-R3's login flow uses, the MCP
resource an access token's audience has to name, the pre-registered native
client a third-party MCP caller uses (the DCR hedge, ADR ident-3), and a dev
person to sign in as.

**Idempotent, and this is the property the criterion pins.** Run it twice on a
fresh instance and the state is identical: every step searches before it
creates, and the second run says `exists` where the first said `created`. There
is no `--force`, no delete-and-recreate, and no "already exists" error — a seed
that could only run once would not be safe in `./scripts/setup.sh`, which is
where it runs.

**What it prints, and what it cannot print twice.** Zitadel shows a client
secret exactly once, at creation. So the first run prints the browser client's
id *and* secret, and the second prints the id alone and says so. That is not a
limitation being worked around; it is the honest output, and the alternative —
rotating the secret on every run so there is always one to print — would break
every `.env` the previous run filled in.

**`--rotate-web-secret` and `--rotate-mcp-secret` are the way back from having
lost one**, and they are flags — two of them, not one — for exactly the reason
above: rotation is not idempotent and must never happen as a side effect of a
seed run, and the browser client's secret and the MCP resource's fail
separately and get pasted into different places. Each mints a new secret for its
own application, prints it once, and leaves the application **id** alone — so
every redirect URI already registered, every audience already naming the
resource, and every other line of `.env` keeps working, which is what makes it
better than the only alternative anybody has otherwise (delete the application,
take a new id, and re-register everything). The previous secret stops working
the moment it runs, and nothing anywhere stores the new one.

**And it sets this deployment's SIGN-IN POSTURE** (ADR ident-8):
whether a stranger may register themselves an account, whether a stranger may
create an organisation, and how many wrong passwords lock one. Those three are
not objects, they are instance-wide policy, and until this command wrote them
every environment shipped with self-registration on, org registration open and
no lockout at all — against `architecture.md` §H, where open signup was
rejected. The `ZITADEL_DEFAULTINSTANCE_*` keys in `compose.yaml` carry the same
values and apply only WHEN AN INSTANCE IS CREATED, so on every Zitadel that
already exists these three calls are the only thing that closes the doors. They
are idempotent the same way everything else here is: compare first, and say
`exists` on the second run.

**It is a door** (house rule 10), so it goes through `apps.accounts.zitadel`
like the activity does, and house rule 27 names this file as one of the three
places that may. It writes no rows of ours at all: the objects it makes are
deployment infrastructure, not any tenant's configuration, and a tenant's
configuration is `sync_identity_config`'s job.

**The dev user is refused outside DEBUG**, exactly as `seed` refuses the
published ones it carries. The variable that holds it ships in `.env.example`,
and a person with a published credential on an internet-facing deployment is
not test data, it is an account.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import CommandError

from apps.accounts import zitadel
from apps.core.management import BaseCommand

# Where Zitadel sends the browser back to after a login. allauth's
# `openid_connect` provider serves its callback under the provider id, and
# W2-R3 registers Zitadel as the one static provider named `zitadel`.
BROWSER_CALLBACK_PATH = "/accounts/oidc/zitadel/login/callback/"
BROWSER_LOGOUT_PATH = "/"

# Where a scripted MCP client is sent back to. A native client runs on somebody
# else's machine and listens on a loopback port it picked at run time, so the
# registered URI has to be the loopback wildcard Zitadel understands rather than
# one port nobody can predict.
MCP_CALLBACK_URIS = (
    "http://localhost:8080/callback",
    "http://127.0.0.1:8080/callback",
)


class Command(BaseCommand):
    help = "Create this deployment's Zitadel project, applications and dev user, idempotently."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--base-url",
            default="",
            help=(
                "Public base URL this product is reached at; the browser client's "
                "redirect URI is built from it (default: PUBLIC_BASE_URL)."
            ),
        )
        parser.add_argument(
            "--skip-user",
            action="store_true",
            help="Make the project and the applications, but no dev person.",
        )
        parser.add_argument(
            "--rotate-web-secret",
            action="store_true",
            help=(
                "Mint a NEW client secret for the browser application and print it "
                "once. The client id is unchanged. The previous secret stops working."
            ),
        )
        parser.add_argument(
            "--rotate-mcp-secret",
            action="store_true",
            help=(
                "Mint a NEW client secret for the MCP resource application and print "
                "it once. The app id is unchanged. The previous secret stops working."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not zitadel.configured():
            raise CommandError(
                "Zitadel is not configured: ZITADEL_ISSUER and ZITADEL_PAT must both be "
                "set. ./scripts/setup.sh writes the PAT into .env from the "
                "zitadel_bootstrap volume; if that volume is gone, reset the instance "
                "(drop the zitadel database and the volume) and run setup again."
            )

        base_url = str(options["base_url"] or settings.PUBLIC_BASE_URL).rstrip("/")

        try:
            org = zitadel.organization()
            self.stdout.write(f"org             {org.get('name', '?')} ({org.get('id', '?')})")

            project = zitadel.ensure_project(name=settings.ZITADEL_PROJECT_NAME)
            self._say("project", settings.ZITADEL_PROJECT_NAME, project)

            browser = zitadel.ensure_web_application(
                project_id=project.id,
                name=settings.ZITADEL_BROWSER_APP_NAME,
                redirect_uris=[f"{base_url}{BROWSER_CALLBACK_PATH}"],
                post_logout_uris=[f"{base_url}{BROWSER_LOGOUT_PATH}"],
                # Zitadel refuses plain-http redirect URIs unless the
                # application says it is in development. A laptop is, and a
                # deployment behind TLS never takes this branch.
                dev_mode=base_url.startswith("http://"),
            )
            self._say("browser client", settings.ZITADEL_BROWSER_APP_NAME, browser)

            resource = zitadel.ensure_api_application(
                project_id=project.id,
                name=settings.ZITADEL_MCP_RESOURCE_NAME,
            )
            self._say("mcp resource", settings.ZITADEL_MCP_RESOURCE_NAME, resource)

            mcp_client = zitadel.ensure_native_application(
                project_id=project.id,
                name=settings.ZITADEL_MCP_CLIENT_NAME,
                redirect_uris=list(MCP_CALLBACK_URIS),
                dev_mode=True,
            )
            self._say("mcp client", settings.ZITADEL_MCP_CLIENT_NAME, mcp_client)

            self._posture(org_name=str(org.get("name", "?")))

            if options["rotate_web_secret"]:
                self._rotate_web_secret(project_id=project.id, app_id=browser.id)

            if options["rotate_mcp_secret"]:
                self._rotate_mcp_secret(project_id=project.id, app_id=resource.id)

            if not options["skip_user"]:
                self._dev_user()
        except zitadel.ZitadelError as error:
            # A management failure is not a traceback anybody wants: the message
            # Zitadel sent is the useful half, and the command already knows
            # what it was trying to do.
            raise CommandError(str(error)) from error

        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "A client secret is shown once, by Zitadel, at creation. Put the "
                "browser client's id and secret in .env as ZITADEL_CLIENT_ID and "
                "ZITADEL_CLIENT_SECRET; a later run cannot print them again. "
                "Lost it? Re-run with --rotate-web-secret: that mints a new "
                "secret and prints it, leaving the project and every application "
                "id untouched."
            )
        )

    def _posture(self, *, org_name: str) -> None:
        """The deployment's sign-in posture, applied to the live instance.

        **The shell door for ADR ident-8**, and the only one: a deployment's
        sign-in posture is set once by an operator editing `.env`, so there is no
        REST route and no MCP tool for it — no runtime persona holds this value
        (rule 17 has no member here; recorded, not exempted). `scripts/setup.sh`
        runs this command on every setup, which is what gets a laptop and a
        deploy the same three answers for free.

        **Why the seed and not the compose keys.** `compose.yaml` and
        `deploy/compose.yaml` carry the same three values as
        `ZITADEL_DEFAULTINSTANCE_*` keys, and those apply WHEN THE INSTANCE IS
        CREATED. Every Zitadel that already exists — this box's, and every
        sibling's — was created before those keys existed and would stay open
        forever. So the compose keys are the belt and these three calls are the
        mechanism.

        **Three doors, not one.** Self-registration and public ORGANISATION
        registration are different doors and closing the first does not close
        the second: measured on the shared development instance, the
        org-registration page answered `200` with a working form while the
        org's own login policy already refused self-registration. Lockout is a
        third: zero attempts is not "unset", it is unlimited.

        **And a fourth door, one level down: the org's OWN login policy.** The
        three above are instance-wide. Zitadel resolves an org's login policy to
        the org's own when it has one and to the instance's when it does not, so
        on any org somebody has already given a policy the instance write above
        governs nothing the hosted page reads. Measured on the shared
        development instance: with the instance policy closed, the org's own
        `allowRegister` alone decided whether `/ui/login/register` served a
        working `<h1>Registration</h1>` form (5690 bytes) or an error page (1762
        bytes). `_org_posture` below is the half that reaches it.

        Each writer compares before it writes, so a second run prints `exists`
        and sends no `PUT` — the same readable idempotence every other line of
        this command has.
        """
        self.stdout.write("")
        login = zitadel.ensure_login_policy(allow_register=settings.ZITADEL_ALLOW_SELF_REGISTRATION)
        self._say(
            "login policy",
            f"self-registration {'on' if settings.ZITADEL_ALLOW_SELF_REGISTRATION else 'OFF'}",
            login,
        )

        self._org_posture(org_name=org_name)

        lockout = zitadel.ensure_lockout_policy(
            max_password_attempts=settings.ZITADEL_MAX_PASSWORD_ATTEMPTS
        )
        self._say(
            "lockout policy",
            f"max password attempts {settings.ZITADEL_MAX_PASSWORD_ATTEMPTS}",
            lockout,
        )

        limits = zitadel.ensure_restrictions(
            is_public_org_registration_disallowed=(
                not settings.ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION
            )
        )
        self._say(
            "restrictions",
            f"public org registration "
            f"{'on' if settings.ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION else 'OFF'}",
            limits,
        )

    def _org_posture(self, *, org_name: str) -> None:
        """This org's OWN login policy — reconciled where it has one, never forked.

        **Only where the org already has a policy of its own.** Zitadel serves
        one endpoint for two states, and `isDefault` is the discriminator: the
        flag is present when the instance default is answering and absent once
        somebody has set an org policy (`zitadel.login_policy`'s docstring
        records how that was measured). So this reads first and writes only in
        the second state.

        **An inheriting org is left inheriting, and that is a decision rather
        than a limitation.** Creating an org policy for an org that has none
        would fork one value into two owners: from that moment the instance
        write above governs every org EXCEPT this one, and a future
        instance-level change would silently not apply here — with nothing
        anywhere saying so. One value, one owner (first principles 9).

        MEASURED on the pinned build, which is why this is a branch and not a
        try/except: `PUT /management/v1/policies/login` against an org with no
        policy of its own answers **404 `Org-M0sif`, "Login Policy not
        found"** — the update endpoint refuses outright, and the only way to
        write one would be the CREATE endpoint, which is exactly the fork this
        branch exists to refuse. (Measured against a throwaway org made and
        left inactive on the shared development instance for the purpose.)

        Full body, like every other writer here: `ensure_login_policy` reads the
        live policy and sends all seventeen fields back with our one changed, so
        the five lifetimes and both factor lists survive byte-identical. A
        partial `PUT` here would zero another product's `passwordCheckLifetime`
        on a shared instance, which is the class of accident the full-body
        convention was written for.
        """
        # The same columns `_say` writes in — an eight-character verb slot and a
        # fifteen-character kind — so the org's line reads down the page with
        # the three above it rather than beside them.
        policy = zitadel.login_policy()
        if not policy:
            self.stdout.write(
                f"unknown  {'login policy':<15} org {org_name}: the answer carried no "
                "policy — nothing reconciled"
            )
            return
        if policy.get("isDefault"):
            self.stdout.write(
                f"{'':<8} {'login policy':<15} org {org_name} inherits the instance policy "
                "(reconciled above)"
            )
            return
        org_login = zitadel.ensure_login_policy(
            allow_register=settings.ZITADEL_ALLOW_SELF_REGISTRATION,
            prefix=zitadel.MANAGEMENT,
        )
        self._say(
            "login policy",
            f"org {org_name}: self-registration "
            f"{'on' if settings.ZITADEL_ALLOW_SELF_REGISTRATION else 'OFF'}",
            org_login,
        )

    def _rotate_web_secret(self, *, project_id: str, app_id: str) -> None:
        """Mint a new browser-client secret and show it. **The one non-idempotent
        thing this command can do**, which is why it takes a flag and says so.

        Everything else here searches before it creates and reports `exists` on
        the second run. This does not and cannot: the point of it is that the old
        secret stops working, so a second run is a second rotation and a second
        secret. The line printed says `rotated`, never `exists`, because a
        command that reported idempotence it does not have is worse than one that
        has none.

        The *idempotent* part is what surrounds it, and that is what the test
        pins: the project, the applications and their ids are the same objects
        before and after, so a rotation repairs a lost secret without disturbing
        anything a `.env` already names.
        """
        rotated = zitadel.rotate_web_application_secret(project_id=project_id, app_id=app_id)
        self.stdout.write(
            f"rotated {'browser secret':<15} {settings.ZITADEL_BROWSER_APP_NAME}  ({app_id})"
        )
        secret = str(rotated.detail.get("clientSecret", ""))
        if secret:
            self.stdout.write(f"                          clientSecret: {secret}")
        self.stdout.write(
            self.style.WARNING(
                "The previous ZITADEL_CLIENT_SECRET has stopped working. Put the "
                "value above in .env now; it cannot be printed again."
            )
        )

    def _rotate_mcp_secret(self, *, project_id: str, app_id: str) -> None:
        """Mint a new MCP-resource secret and show it. **The second non-idempotent
        thing this command can do**, and a separate flag from the browser one.

        Separate, because the two credentials fail separately and are pasted into
        different places: rotating the browser secret when what was lost was the
        resource's would take the login flow down to fix something else. The
        rotation this repository already had covered only the client a person
        signs in through, so the resource server's own secret — the credential an
        access token's audience is validated against — was the one thing here
        with no way back from being lost but deleting the application and
        re-registering every audience that names its id.

        Everything else in this command searches before it creates and reports
        `exists` on the second run; this does not and cannot, for the same reason
        `_rotate_web_secret` cannot: the previous secret stopping work is the
        point, so a second run is a second rotation. The line says `rotated`,
        never `exists`.

        **Printed once and stored nowhere.** No row of ours holds it, nothing
        logs it, and the value is not read back out of Zitadel afterwards —
        `apps/accounts/zitadel.py` is the only module that speaks to the
        management API at all (house rule 27) and it hands the plaintext
        straight through to this line.
        """
        rotated = zitadel.rotate_api_application_secret(project_id=project_id, app_id=app_id)
        self.stdout.write(
            f"rotated {'mcp secret':<15} {settings.ZITADEL_MCP_RESOURCE_NAME}  ({app_id})"
        )
        secret = str(rotated.detail.get("clientSecret", ""))
        if secret:
            self.stdout.write(f"                          clientSecret: {secret}")
        self.stdout.write(
            self.style.WARNING(
                "The previous MCP resource secret has stopped working. Put the "
                "value above wherever your deployment holds it now; it cannot be "
                "printed again."
            )
        )

    def _dev_user(self) -> None:
        email = settings.ZITADEL_DEV_USER_EMAIL
        if not settings.DEBUG:
            self.stdout.write(
                self.style.WARNING(
                    f"skipped user    {email} — DEBUG is off and its password is "
                    "published in .env.example"
                )
            )
            return
        user = zitadel.ensure_human_user(
            username=email,
            email=email,
            first_name="Dev",
            last_name="Person",
            password=settings.ZITADEL_DEV_USER_PASSWORD,
        )
        self._say("dev user", email, user)

    def _say(self, kind: str, name: str, resource: zitadel.Resource) -> None:
        """One line per object: what it is, what it is called, and its id.

        `created` versus `exists` is the whole readable half of idempotence — a
        second run that printed `created` again would be telling you it had made
        a second object.
        """
        verb = "created" if resource.created else "exists "
        self.stdout.write(f"{verb} {kind:<15} {name}  ({resource.id})")
        for key in ("clientId", "clientSecret"):
            value = str(resource.detail.get(key, ""))
            if value:
                self.stdout.write(f"                          {key}: {value}")
