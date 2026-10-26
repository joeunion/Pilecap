"""`manage.py zitadel_reconcile` — read the instance, then ask for what disagrees.

    uv run python manage.py zitadel_reconcile --dry-run
    uv run python manage.py zitadel_reconcile --as operator@example.com

**ADR ident-2's other half, and its trigger has fired.** The ADR shipped the
tripwire (`manage.py zitadel_audit`) and deliberately did not ship the repairer,
naming the trigger: *first observed drift, or first production deploy, whichever
comes first.* Both happened. A one-field console change to this deployment's own
browser application lands a person on raw JSON at the identity platform and
neither the audit nor the seed noticed; a one-way sync locked an owner out of the
sibling product for a morning. So this exists, and it is a **second command**
rather than a flag on the audit: the audit's read-only-ness is a property its own
tests hold it to, and a writing path inside the one command a deploy step trusts
to change nothing is not a trade worth making.

**It reads through the audit's own sections — one read, not two.** Every line
below the header comes out of `zitadel_audit.read_report`, byte-identical, and
the findings that walk beside those lines are what this command acts on. Two
readers of one instance that phrase what they saw differently are two tripwires
to keep in step, and the one that drifts is the one nobody runs weekly.

**Every repair is a SERVICE call, never a management call — with one declared
exception** (house rules 10 and 27). For the three kinds that have a row or an
environment intent, the service writes the intent and starts
`SyncIdentityConfigWorkflow` on commit; the run's activity is the only thing in
this codebase that reaches Zitadel's management API. That is what keeps a
reconcile of ten disagreements from holding one transaction open across ten
calls to somebody else's API (principle 8).

The `applications` road runs `zitadel_seed`'s writers: ADR ident-2's declared exception, since
the project and its applications have no row to be an intent. `--dry-run` calls nothing.

**The ownership table. One entry per identity fact this deployment has an
opinion about** — who is authoritative, why a copy exists, which way a
disagreement is settled, how staleness is noticed, and what `kind` of ask closes
it. A fact with no kind is a fact this command prints and never touches, and it
is here for the same reason the others are: a fact with no entry is
indistinguishable from a fact nobody thought about (principle 9). The entries
run down the page rather than across it because five fields of argued prose do
not fit in six columns of 100, and a cell trimmed until it fits is a cell
nobody can act on.

**a tenant's realm** — `kind`: `identity_home`
  authority   our `IdentityHome` row — one per tenant, written `pending` when
              the tenant is created and `own_org` when its realm lands.
  the copy    the tenant's organisation at Zitadel, the project's grant to
              it, and its own login policy.
  settled     the row wins: a tenant with no home, a `pending` one, a realm
              the platform no longer has or one not granted the project is
              asked for again (`services.start_identity_home`, with
              `observed`), which is how a tree that predates realms homes its
              tenants at its next deploy.
  staleness   the audit's realm section and its `n of n tenants homed`.

**a customer's federation** — `kind`: `sso_connection`
  authority   our `SsoConnection` row.
  the copy    the Zitadel IdP inside the tenant's realm, linked to that
              realm's login policy — and, while the row says `enforced`, that
              policy with the password off and the provider required.
  settled     the row wins. A console edit to the name or the issuer is
              drift, and so is a realm whose policy disagrees with `enforced`
              either way; each is re-asked with `observed`.
  staleness   the audit's connection walk and its enforced line, plus the
              row's own `sync_state`.

**an IdP no row of ours names** — `kind`: none
  authority   Zitadel — a sibling product on a shared instance, or a person.
  the copy    none. We hold nothing about it.
  settled     never touched, and never deleted. A deployment may legitimately
              carry providers this product did not create.
  staleness   the `unclaimed` count, which is what makes somebody go and look.

**the workforce door** — `kind`: `workforce_provider`
  authority   the ENVIRONMENT (`GOOGLE_*`). There is no row, and inventing one
              nobody owns would be worse than saying so.
  the copy    the org-level Google IdP, and the Google client id it points at.
  settled     the environment wins BOTH ways: configured here and absent there
              → materialised; live there and switched off here → DEACTIVATED;
              a re-pointed client id → re-pointed back.
  staleness   the audit's workforce section.

**the hosted sign-in screen's look** — `kind`: `identity_branding`
  authority   the active `IdentityBranding` row.
  the copy    the org label policy, which is what the screen is drawn from.
  settled     the row wins on the fields it states; the columns it leaves
              blank stay Zitadel's, because a blank column is not an opinion.
  staleness   the audit's branding section.

**the console's own surfaces** — `kind`: none
  (label-policy fields no row states; the org login policy's other fields;
  how many organisations the instance holds)
  authority   Zitadel, and whoever opened the console.
  the copy    none.
  settled     observed, never judged. Reaching a verdict would mean building
              intent machinery to guard a surface nothing writes (ADR
              ident-2 amended, whose trigger is a product managing them
              through services).
  staleness   printed on every run, and moving no exit code.

**the instance-wide SMTP sender** — `kind`: none
  authority   whoever set it. On a shared instance that is a sibling product,
              named by the configuration's own `description`. **This
              deployment declares no SMTP intent.**
  the copy    none.
  settled     never written. A foreign owner is printed AS foreign and
              counted beside the verdict — a fact about an unowned surface,
              still not a verdict on it.
  staleness   printed on every run.

**the sign-in posture** — `kind`: `posture`, whose road is NOT this command
  (self-registration, password lockout, public org registration, and this
  org's own `allowRegister`)
  authority   the ENVIRONMENT (ADR ident-8).
  the copy    the instance and org policies.
  settled     the environment wins both ways — by `manage.py zitadel_seed`'s
              writers. This command reports the delta and names that road.
  staleness   the audit's posture section.

**the project and application NAMES** — `kind`: `applications`
  authority   settings.
  the copy    the Zitadel objects, found or created by name.
  settled     a missing project or application is created by the declared
              writer (`manage.py zitadel_seed`, which this command runs). A
              changed NAME is a SECOND object, printed with both ids, never a
              rename and never a deletion (ADR platform-1) — and while two
              projects bear the declared name this kind is REFUSED, because a
              writer aimed at the wrong one reconfigures a sibling
              deployment's sign-in.
  staleness   the audit's applications section.

**the browser client's redirect and post-logout URIs, `devMode`** — `kind`:
`applications`
  authority   settings (`core.surfaces.surface_base_urls`).
  the copy    the application's OIDC config.
  settled     settings win both ways, including by REMOVAL — a URI no longer
              declared is cleared, because an application still accepting a
              callback on an origin the deployment has moved off is a redirect
              target somebody else may come to own. The writer sends the
              resource's whole field set (ADR ident-8), so the fields nobody
              here manages survive byte-identical. A hijacked redirect URI is
              the canonical case: it lands a person on raw JSON at the identity
              platform, upstream of any page of ours.
  staleness   the audit's applications section.

**which login UI each OIDC client declares** (`loginVersion`) — `kind`:
`applications`
  authority   settings, through `zitadel_seed.declared_login_base_uri` — one
              function, read by the writer, by the audit and by nothing else.
  the copy    the application's `loginVersion`, which is what Zitadel's
              `/oauth/v2/authorize` reads to decide where to send a person.
  settled     settings win BOTH ways. A declaration we do not make is cleared
              — the writer sends `loginVersion: null` in the full body and the
              key is gone — because a v2 declaration nobody here made sends
              everybody to a URL this deployment does not serve, upstream of
              any page of ours, exactly like the hijacked redirect URI above.
              Today the declaration is `None` for every deployment; rung A5's
              `SIGN_IN_DOOR` is what makes it a URI.
  staleness   the audit's applications section, per OIDC client.

**the manager role the login-v2 finalize needs** — `kind`: `login client`
  authority   this design. The intent is "always held", on every deployment,
              whichever sign-in page it serves: the role authorises a call a
              hosted-page deployment never makes, so holding it costs nothing
              and NOT holding it makes flipping `SIGN_IN_DOOR` a two-step move
              with a console visit in the middle.
  the copy    `IAM_LOGIN_CLIENT` on the machine user the PAT belongs to,
              which Zitadel names and no `.env` copies.
  settled     granted, never removed, by `manage.py zitadel_seed`'s writer
              (`zitadel.ensure_instance_member_role`), which sends the UNION
              of the roles the credential already holds — a reconciler that
              could compute a role list would eventually compute one without
              `IAM_OWNER` on the credential it reconciles with.
  staleness   the audit's login client section. Its absence is invisible from
              everywhere else: every seed, audit and sync keeps working and
              sign-in fails at the last hop with `403 AUTH-AWfge`.

**the MCP resource's and MCP client's own configuration** — `kind`: none
  authority   settings, in principle.
  the copy    those applications' configs.
  settled     EXISTENCE is judged and nothing else: no writer reconciles
              their fields yet, and reporting drift on a field with no road
              is a finding an operator cannot act on.
  staleness   the audit's applications section, by absence only.

**client ids and secrets; the MCP audience** — `kind`: `env copies`, which has
no road and must not acquire one
  authority   Zitadel mints them.
  the copy    `.env`'s `ZITADEL_CLIENT_ID` and `ZITADEL_MCP_AUDIENCE`.
  settled     never written from here — a command that edited the operator's
              environment file would be writing the one artifact they own
              outright. Both values are printed side by side, a difference is
              drift with the remedy in words, and UNSET is not a difference:
              a checkout with no browser sign-in configured must not read as a
              broken deployment. Either the project id or the API
              application's client id satisfies the audience, because Zitadel
              puts both in `aud`.
  staleness   printed beside the environment's on every run.

**a person, and the identity join** — `kind`: none, and said rather than implied
  authority   Zitadel owns the credential; our `User` is minted at sign-in.
  the copy    the join's rows (`SsoIdentity` with no connection), one per realm.
  settled     NOT reconciled. Revocation flows one way, and a command that
              wrote a chosen subject onto a `User` would be a door for
              claiming somebody else's identity.
  staleness   out of scope, and that is the entry.

**What is NOT built, and the trigger.** A Temporal Schedule around this is one
`ScheduleDeclaration` and it is deliberately not written. A scheduled repairer
of drift that only a console can cause, on a deployment whose console has one
operator, guards nothing most nights and repaints a screen at 3am on the one
night somebody was halfway through a change. The trigger is printed on every
run so the decision is reversible by evidence: **a drift found in production
that nobody in this deployment caused.** Until then this is a hand command and
a deploy step, which is what `--dry-run` and the exit codes are shaped for.

**Exit 0 asked (or nothing to ask) · 1 a disagreement is still open · 2 could
not look.** The house semantics: 2 outranks a pass, and it is the one an
automated caller must be able to tell from a disagreement. A `--dry-run` over an
open delta is 1 by construction — it asked for nothing — and a delta whose road
is another command's stays 1 after a real run, because a reconciler that exited
0 over what it left behind would be certifying an instance it did not fix.

**Could not look means nothing is asked for, for any kind.** A surface this
command JUDGES that would not answer stops the whole run (principle 4): a
partial read is not a small read, and repairing what was visible while blind to
one surface leaves an instance nobody can reason about afterwards. The
console's own surfaces are the declared exception — they are printed and judged
by nothing, so a sender that could not be read is a line this command could not
print rather than a fact a repair could be wrong about.
"""

from __future__ import annotations

from typing import Any

from django.core.management import call_command
from django.core.management.base import CommandError

# rule-27: the reconciler is a shell door onto the same read `zitadel_audit`
# makes, and it needs the client for exactly two things — `configured()`, so an
# unconfigured deployment is exit 2 rather than a traceback, and `ZitadelError`,
# so a surface that would not answer is could-not-look rather than a crash. It
# writes nothing: every repair below is a service call, and the management call
# happens later, in the activity, where a failure is a Temporal retry.
from apps.accounts import zitadel
from apps.accounts.management.commands.zitadel_audit import (
    APPLICATIONS_KIND,
    DRIFT,
    ENV_COPY_KIND,
    IDENTITY_HOME_KIND,
    LOGIN_CLIENT_KIND,
    POSTURE_KIND,
    Finding,
    blind_spot_lines,
    read_report,
)
from apps.accounts.models import SsoConnection, User
from apps.accounts.selectors import list_stale_staff_joins
from apps.accounts.services import (
    retire_stale_staff_join,
    set_identity_branding,
    start_identity_home,
    sync_identity_config,
    sync_workforce_identity_config,
)
from apps.accounts.types import (
    KIND_IDENTITY_BRANDING,
    KIND_SSO_CONNECTION,
    KIND_WORKFORCE_PROVIDER,
)
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.exceptions import DomainError
from apps.core.management import BaseCommand
from apps.core.models import Tenant

# The kinds this command has a road for. It is a subset of the ownership table's
# `kind` column on purpose, and the table says why for each absence: the
# posture's road is the seed's writers, the applications' is another rung's
# section, and a person's identity join has no road at all by decision.
#
# Derived nowhere and declared here, because "which repairs exist" is a fact
# about THIS command rather than about the vocabulary: `types.py` names the kinds
# the workflow can materialise, and a kind can be materialisable long before
# anything knows how to notice it needs materialising.
REPAIRED_KINDS: tuple[str, ...] = (
    IDENTITY_HOME_KIND,
    KIND_SSO_CONNECTION,
    KIND_WORKFORCE_PROVIDER,
    KIND_IDENTITY_BRANDING,
    APPLICATIONS_KIND,
    LOGIN_CLIENT_KIND,
)

# The one repaired kind whose road is NOT a service ask and a run, and the
# reason it is the exception rather than the pattern: the project, the browser
# client and the two MCP objects have no row to state an intent on — their
# declared values ARE settings — so there is nothing for a service to write and
# nothing for a workflow to carry. `manage.py zitadel_seed`'s writers are the
# one door onto them, and they are a shell door, so this road runs that command
# and says so on the line it prints. Every other kind's repair leaves this
# process making no management call at all.
SEED_ROAD_KINDS: tuple[str, ...] = (APPLICATIONS_KIND, LOGIN_CLIENT_KIND)

# What the reconciler will not decide. Two projects bearing the declared name is
# what a checkout leaves behind when somebody changes `ZITADEL_PROJECT_NAME` and
# changes it back, and a writer aimed at the wrong one of two same-named
# projects reconfigures a SIBLING deployment's sign-in (ADR platform-1). There
# is no safe automatic answer, so the kind is refused while the state holds —
# `applications_section` marks that finding, and this is the mark.
AMBIGUOUS_PROJECT = "ambiguous-project"

# What the command says about the schedule it is not. Printed every run; see the
# module docstring's "What is NOT built".
NOT_BUILT = (
    "not built    a Temporal SCHEDULE around this command. It is a hand command and a "
    "deploy step; the trigger for scheduling it is a drift found in production that "
    "nobody in this deployment caused (ADR ident-2)."
)


class Command(BaseCommand):
    help = "Ask the services to close what zitadel_audit reports. Makes no management call."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print the delta and ask for nothing. Exits 1 while a delta is open.",
        )
        parser.add_argument(
            "--kind",
            default="",
            choices=("", *REPAIRED_KINDS),
            help="Only repair one kind. Anything left over still exits 1.",
        )
        parser.add_argument(
            "--tenant",
            default="",
            help="Only walk one tenant's connections, by slug — the audit's own flag.",
        )
        parser.add_argument(
            "--as",
            dest="acting_email",
            default=None,
            help=(
                "Who to attribute the asks to. Omit to act as the system. A platform "
                "fact needs deployment.configure; a customer's connection needs "
                "sso_connection.update in that tenant."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not zitadel.configured():
            raise CommandError(
                "Zitadel is not configured: ZITADEL_ISSUER and ZITADEL_PAT must both "
                "be set. There is nothing to read, so there is nothing to reconcile.",
                returncode=2,
            )

        user = self._acting_user(options["acting_email"])
        tenant_slug = str(options["tenant"]).strip().lower()
        only = str(options["kind"]).strip()
        dry_run = bool(options["dry_run"])

        try:
            report = read_report(tenant_slug=tenant_slug)
        except zitadel.ZitadelError as error:
            # The audit turns this into exit 1 through a plain `CommandError`;
            # here it is explicitly the could-not-look class, because the caller
            # is about to decide whether an instance was repaired.
            raise CommandError(str(error), returncode=2) from error

        for line in report.lines:
            self.stdout.write(line)
        self.stdout.write("")
        for line in blind_spot_lines():
            self.stdout.write(line)
        self.stdout.write("")
        self.stdout.write(NOT_BUILT)
        self.stdout.write("")

        if report.unreadable:
            for finding in report.unreadable:
                self.stdout.write(self.style.WARNING(f"blind       {finding.line.strip()}"))
            raise CommandError(
                f"{len(report.unreadable)} surface(s) this command judges could not be read, "
                "so nothing was asked for — for any kind. A partial read is not a small "
                "read: repairing what was visible would leave an instance nobody can "
                "reason about. Fix the read and run it again.",
                returncode=2,
            )

        deltas = [one for one in report.findings if one.verdict == DRIFT]
        mine = [
            one
            for one in deltas
            if one.kind in REPAIRED_KINDS
            and only in ("", one.kind)
            and one.key != AMBIGUOUS_PROJECT
        ]
        left = [one for one in deltas if one not in mine]

        self._retire_stale_staff_joins(user=user, dry_run=dry_run)

        if dry_run:
            for finding in mine:
                self.stdout.write(f"would ask   {finding.kind} — {finding.line.strip()}")
            self._say_what_is_left(left, only=only)
            self.stdout.write(
                f"{len(mine)} delta(s) this command can close, 0 asked (--dry-run). "
                "Re-run without --dry-run to ask for them."
            )
            if deltas:
                # The same shape the audit uses: the report already said
                # everything, and a traceback on top of it would read as a crash.
                raise SystemExit(1)
            return

        asked = 0
        for finding in mine:
            said = self._ask(finding, user=user)
            self.stdout.write(f"asked       {finding.kind} — {said}")
            asked += 1
        self._say_what_is_left(left, only=only)
        self.stdout.write(
            self.style.SUCCESS(
                f"{asked} asked, {len(left)} left. The runs materialise them; watch them "
                "in Temporal, then re-read with `manage.py zitadel_audit`."
            )
        )
        if left:
            raise SystemExit(1)

    def _retire_stale_staff_joins(self, *, user: User | None, dry_run: bool) -> None:
        """Each `staff` join row a tenant realm's row now supersedes: named, then retired."""
        for identity in list_stale_staff_joins():
            said = f"staff join for subject {identity.subject} — its realm row stands"
            if dry_run:
                self.stdout.write(f"would retire {said}")
                continue
            retire_stale_staff_join(
                identity=identity, actor=self._platform_actor(user), tenant=None
            )
            self.stdout.write(f"retired     {said}")

    def _say_what_is_left(self, left: list[Finding], *, only: str) -> None:
        """Name every delta this command is walking away from, and WHY.

        A count would do for arithmetic and not for the operator: "1 left" over a
        posture drift is indistinguishable from "1 left" over a kind `--kind`
        filtered out, and the two are different afternoons. Three reasons, each
        with its own sentence — the road is another command's, the road exists
        and was not selected, or there is no road at all.
        """
        for finding in left:
            if finding.key == AMBIGUOUS_PROJECT:
                whose = (
                    "REFUSED — two projects bear the declared name and a writer aimed at "
                    "the wrong one reconfigures a sibling deployment's sign-in; point "
                    "ZITADEL_PROJECT_NAME at the one this deployment owns"
                )
            elif finding.kind == ENV_COPY_KIND:
                whose = (
                    "yours to edit — .env is the operator's own file and no command here writes it"
                )
            elif only and finding.kind in REPAIRED_KINDS:
                whose = f"--kind {only} did not select {finding.kind}; re-run for it"
            elif finding.kind == POSTURE_KIND:
                whose = "`manage.py zitadel_seed` writes the posture, not this command"
            else:
                whose = f"no road in this command for kind {finding.kind or 'none'}"
            self.stdout.write(self.style.WARNING(f"left        {whose} — {finding.line.strip()}"))

    def _acting_user(self, email: str | None) -> User | None:
        """Who `--as` names, or nobody.

        A named address that is not there is a refusal rather than a quiet fall
        back to the system actor: an operator who mistyped their own email would
        otherwise get a reconcile attributed to "the shell" and no way to know.
        """
        if not email:
            return None
        user = User.objects.filter(email=str(email).strip().lower()).first()
        if user is None:
            raise CommandError(f"No user with email {email}.")
        return user

    def _ask(self, finding: Finding, *, user: User | None) -> str:
        """One repair, asked for through the service that owns the fact.

        Returns what to print. Every branch here is a service call and none of
        them touches Zitadel; a `DomainError` out of one — a refusal, a missing
        row, a permission — becomes a `CommandError`, because the operator asked
        for this at a terminal and a traceback is not an answer.
        """
        if finding.kind in SEED_ROAD_KINDS:
            # The one road that is a command rather than a service ask. It is
            # run with `--skip-user` because a reconcile is not a first setup
            # and minting a development person is not a repair.
            #
            # **It reaches further than this kind, and the line says so.** The
            # seed's own run also writes the sign-in posture, which is a delta
            # this command reports and declines to own (the ownership table says
            # the posture's road is exactly these writers). So a posture delta
            # printed as `left` may be closed by the time this returns, and the
            # only honest thing to do about that is to name it and tell the
            # reader to look again — an exit status computed from a read that is
            # now one repair old cannot say it for them.
            call_command("zitadel_seed", "--skip-user", stdout=self.stdout)
            return (
                "ran manage.py zitadel_seed — the declared writer for these objects. "
                "It writes the sign-in posture too, so re-read with `manage.py "
                "zitadel_audit` rather than trusting this run's exit status about it"
            )
        try:
            if finding.kind == KIND_IDENTITY_BRANDING:
                row = set_identity_branding(
                    actor=self._platform_actor(user), tenant=None, observed=finding.line
                )
                return f"sign-in branding ({row.pk}) re-asked against the live intent row"
            if finding.kind == IDENTITY_HOME_KIND:
                tenant = Tenant.objects.filter(slug=finding.key).first()
                if tenant is None:
                    return f"tenant {finding.key} is gone since the read; nothing asked"
                start_identity_home(
                    tenant=tenant,
                    actor=self._home_actor(user, tenant=tenant),
                    observed=finding.line,
                )
                return f"realm for {tenant.slug} asked for"
            if finding.kind == KIND_WORKFORCE_PROVIDER:
                asked = sync_workforce_identity_config(
                    actor=self._platform_actor(user), tenant=None, observed=finding.line
                )
                return f"workforce door, run {asked.run.workflow_id}"
            connection = (
                SsoConnection.objects.select_related("tenant").filter(pk=finding.key).first()
            )
            if connection is None:
                # A row deleted between the read and the ask. Reported, not
                # repaired: the delta the reader saw no longer describes
                # anything, and inventing a replacement row would be worse.
                return f"connection {finding.key} is gone since the read; nothing asked"
            sync_identity_config(
                tenant=connection.tenant,
                actor=self._connection_actor(user, connection=connection),
                connection=connection,
                observed=finding.line,
            )
            return f"{connection.tenant.slug}/{connection.name} re-asked"
        except DomainError as error:
            raise CommandError(f"{finding.kind}: {error.detail}") from error

    @staticmethod
    def _platform_actor(user: User | None) -> Actor:
        """The deployment's own facts: the workforce door and the sign-in screen.

        No tenant, because neither belongs to a customer, and the run these lead
        to is the platform's (ADR workflows-3). The `tenant` a service takes
        alongside is the audit anchor and is deliberately left out here: a
        reconcile is not done "in" any workspace, and filing its receipt in one
        would put the deployment's work in a customer's ledger.
        """
        if user is None:
            # Nobody clicked this — a deploy step or a cron line. `authz.allows`
            # lets the system past before any policy runs, which is right and is
            # also why `--as` is the better habit on a shared deployment.
            return system_actor()
        return actor_for(user=user, tenant=None, kind="human")

    @staticmethod
    def _home_actor(user: User | None, *, tenant: Tenant) -> Actor:
        """A tenant's realm: the system inside that tenant, or the named operator."""
        if user is None:
            return system_actor(tenant)
        return actor_for(user=user, tenant=tenant, kind="human")

    @staticmethod
    def _connection_actor(user: User | None, *, connection: SsoConnection) -> Actor:
        """One customer's federation: an actor inside that customer's tenant.

        `sso_connection.update` is checked at the tenant's root organization, so
        the actor has to carry the tenant — which also means a `--as` naming
        somebody with no standing in that tenant is refused, and that is the
        correct answer rather than an inconvenience. The system actor is what a
        deploy step gets.
        """
        if user is None:
            return system_actor(connection.tenant)
        return actor_for(user=user, tenant=connection.tenant, kind="human")
