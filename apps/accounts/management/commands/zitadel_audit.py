"""`manage.py zitadel_audit` — does Zitadel still say what our rows say?

    uv run python manage.py zitadel_audit

**The honest half of ADR ident-2.** The enforceable half is house rule 27: no
module outside `apps/accounts/zitadel.py` reaches the management API, so nothing
*in this codebase* can write identity configuration behind the services' back. A
check cannot see Zitadel's console, and somebody with an admin login can change
anything in it. So the console is a declared blind spot, and this is the
tripwire: a read-only report saying where the two disagree.

**It changes nothing, and that is a property rather than a promise.** Every call
it makes is a `GET` or a `_search` (`apps/accounts/zitadel.py`, "reads"), and the
test drives it against an instance a raw API call has deliberately mutated —
standing in for somebody in the console — and asserts both halves: the drift is
reported, and the instance afterwards is byte-identical to the instance before.
Repairing is somebody else's command, and that separation is the point:
`manage.py zitadel_reconcile` reads through the section functions in this module
— one read, not two — and asks the services for the repairs their findings name.
The ADR's trigger for a reconciler at all (first observed drift, or first
production deploy) has fired; the trigger for SCHEDULING one has not, and the
reconciler prints it.

**Three populations judged, not one.** Every customer `SsoConnection` is
compared against the IdP its row names; the **workforce** door is compared
against the environment, because it has no row to name anything with
(`workforce_section`); and, since the branding row landed, the deployment's own
**sign-in screen** is compared against the `IdentityBranding` intent row
(`branding_section`) — the first surface this audit can judge that is neither
a customer's row nor bare environment, and the whole reason it can reach a
verdict at all where the section below cannot: there is now a row to disagree
with. Before the workforce section, the one door the people running this
product sign in through was the one thing rule 27's blind spot covered
completely, since the row-by-row walk had nothing to start from; before the
branding section, the hosted screen's look was the same gap.

**And a fourth section that reaches no verdict at all.** What is left with no
intent behind it at all is *observed and printed*, never judged
(`console_section`): the instance's SMTP sender, how many organisations the
instance holds, and every field of this org's own login policy except the one
the posture section judges. No product manages any of them through services, so
no intent exists to disagree with, and reaching a drift verdict on them would
mean inventing that machinery to guard a surface nothing writes. They are GETs
and a `_search` like everything else here, so the change-nothing property covers
them unchanged, and they add nothing to the exit status. ADR ident-2's amendment
records the decision and the trigger that would revisit it — the first product
managing login policy or SMTP through services. Branding graduated out of this
section for exactly that reason, and so did this org's `allowRegister`: they are
no longer surfaces nothing writes. **The SMTP sender's OWNER is named and
counted beside the verdict** — a fact about an unowned surface, still not a
verdict on it: the report used to print another product's `Set by …` string as
colour and then say "Zitadel agrees with every row" over it.

**What it cannot see is now PRINTED beside the verdict** (`blind_spot_lines`),
rather than left in this docstring where only a maintainer would find it: it
compares what our rows *declare*, and a class of Zitadel configuration this
product never writes — an instance-level policy beyond the posture's three, a
second organisation's own policies, an IdP created by hand under a name no row
claims — is invisible to it, except for the summary lines counting IdPs Zitadel
has that no row names and organisations the instance holds. That is the
declared blind spot on rule 27, and the person reading a clean report is the
person who most needs to know what "clean" covers, which is why it prints on
every run and under both verdicts. The workforce section narrows that blind spot
by one door and does not close it: the domain list itself is not in Zitadel to
compare against (ADR ident-6), so what is reconciled there is the door's
existence and the Google project it points at.

Exit status is the report's verdict: **0 when the two agree, 1 when they do
not**, so `zitadel_audit` can be a cron line or a deploy step rather than
something a person has to read. It never exits 2 — this is a tripwire, not a
gate leg.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from django.conf import settings
from django.core.management.base import CommandError

from apps.accounts import realms, zitadel

# The DECLARED values this section compares against, imported from the command
# that writes them rather than restated here: the whole of the comparison is
# "does Zitadel still hold what the seed declares", and a second copy of those
# constants would be the one thing the comparison cannot afford. A command
# importing a command is cheap — neither module touches the ORM or Temporal at
# import time — where a command importing an ACTIVITY would drag Temporal into
# a shell process.
from apps.accounts.management.commands import zitadel_seed as seed
from apps.accounts.models import IdentityBranding, IdentityHome, SsoConnection
from apps.accounts.realm import LoginPolicy
from apps.accounts.selectors import get_tenant_realm, get_workforce_domains
from apps.accounts.types import (
    KIND_IDENTITY_BRANDING,
    KIND_SSO_CONNECTION,
    KIND_WORKFORCE_PROVIDER,
)
from apps.core.management import BaseCommand
from apps.core.models import Tenant
from apps.core.surfaces import surface_base_urls

# --- what a section answers with ---------------------------------------------
#
# The sections used to print straight to `self.stdout`, which was the whole of
# the report and is no longer: `manage.py zitadel_reconcile` reads the same
# surfaces to decide what to ask for, and two readers of one instance that
# phrase what they saw differently are two tripwires to keep in step. So a
# section RETURNS what it found and the caller decides what to do with it — the
# audit prints it, the reconciler prints it and then acts on it. One read, not
# two.

# The five verdicts a line can carry. `AGREES` and `DRIFT` are the audit's two
# and always were. `UNREADABLE` used to be a sentence with no status behind it
# ("could not look" is not "nothing there"), and it needs one now because the
# reconciler must refuse to repair anything at all when a surface it judges
# would not answer. `OBSERVED` is the section that reaches no verdict, and
# `FOREIGN` is an observed fact whose owner is somebody else — still unjudged,
# because no intent of ours states it, and no longer silently counted as
# agreement.
AGREES = "agrees"
DRIFT = "drift"
UNREADABLE = "unreadable"
OBSERVED = "observed"
FOREIGN = "foreign"

# The posture's kind. It is NOT one of `types.py`'s `KIND_*` constants and must
# not become one: those name classes of work `SyncIdentityConfigWorkflow` can
# materialise, and the posture's road is the seed's own writers
# (`manage.py zitadel_seed`), which are a shell door rather than a run. The
# reconciler carries this string so it can say WHICH delta it is leaving alone
# and name the command that closes it — a delta with no road still has to be
# visible.
POSTURE_KIND = "posture"

# The applications' kind — the deployment's own project, browser client, MCP
# resource and MCP client. Its road is `manage.py zitadel_seed`'s writers, which
# is a shell door rather than a run, so this is not a `types.py` `KIND_*` either.
APPLICATIONS_KIND = "applications"

# The kind for the manager role the machine credential needs before a login-v2
# finalize is allowed at all. Its road is the seed's writers, exactly as the
# applications' is, but it is NOT that kind: a role is not an object on a
# project, and folding it in would make `--kind applications` a flag whose name
# no longer says what it repairs. Like the posture and the applications, it is
# not a `types.py` `KIND_*` — nothing materialises it through a run.
LOGIN_CLIENT_KIND = "login client"

# The kind for the two values Zitadel MINTED that `.env` keeps a copy of. It has
# no road at all and must not acquire one: a command that edited the operator's
# environment file would be writing the one artifact they own outright. The
# reconciler carries this string so it can name the remedy in words instead of
# leaving a delta looking unattended.
ENV_COPY_KIND = "env copies"

# A tenant's realm. Asked for through `services.start_identity_home` — the
# reconciler's road for a tenant whose realm is missing, pending or gone — and
# a workflow of its own rather than a `types.py` `KIND_*` of the configuration
# sync, which is why it is spelled here.
IDENTITY_HOME_KIND = "identity_home"


class Finding(NamedTuple):
    """One fact the report reached a verdict about, and what would close it.

    `kind` is the ownership table's own column — the class of ask that repairs
    this fact — and it is EMPTY for everything nothing repairs: the console's
    surfaces, the organisation count, a stranger IdP. An empty kind is what
    makes "this command prints it and never touches it" a thing the code says
    rather than a thing the docstring claims.

    `line` is the exact sentence printed, carried rather than rebuilt, so the
    reconciler's `observed` argument is the audit's own words and a reader
    comparing the two reports is comparing one string.
    """

    verdict: str
    kind: str
    key: str
    line: str


class Section(NamedTuple):
    """One region of the report: its lines, its disagreements, its findings.

    `lines` and `drift` are the two every caller needs and the two this shape
    is named for. `findings` defaults to empty because two sections legitimately
    have none — the header and the stranger count are lines about a population
    rather than verdicts about a fact.
    """

    lines: list[str]
    drift: int
    findings: tuple[Finding, ...] = ()


class Report(NamedTuple):
    """Every section, joined — what one read of the instance produced."""

    lines: list[str]
    drift: int
    findings: tuple[Finding, ...]

    @property
    def observed(self) -> int:
        """How many surfaces were looked at and deliberately not judged."""
        return sum(1 for one in self.findings if one.verdict in (OBSERVED, FOREIGN))

    @property
    def foreign(self) -> int:
        """How many of those belong to somebody other than this product."""
        return sum(1 for one in self.findings if one.verdict == FOREIGN)

    @property
    def unreadable(self) -> tuple[Finding, ...]:
        """The surfaces a verdict was owed on and could not be reached.

        The reconciler refuses to ask for anything when this is non-empty; the
        audit prints them and exits on the drift count, as it always has.
        """
        return tuple(one for one in self.findings if one.verdict == UNREADABLE)


class Command(BaseCommand):
    help = "Report where Zitadel and our identity-config rows disagree. Changes nothing."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--tenant",
            default="",
            help="Only audit one tenant's connections, by slug.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not zitadel.configured():
            raise CommandError(
                "Zitadel is not configured: ZITADEL_ISSUER and ZITADEL_PAT must both "
                "be set. There is nothing to compare against."
            )

        try:
            report = read_report(tenant_slug=str(options["tenant"]).strip().lower())
        except zitadel.ZitadelError as error:
            raise CommandError(str(error)) from error

        for line in report.lines:
            self.stdout.write(line)
        self.stdout.write("")
        for line in blind_spot_lines():
            self.stdout.write(line)
        self.stdout.write("")
        if report.drift:
            self.stdout.write(
                self.style.WARNING(f"{report.drift} disagreement(s). Nothing was changed.")
            )
            # A non-zero exit so this can be a deploy step. `SystemExit` rather
            # than `CommandError`, because the report already said everything
            # and a traceback-shaped error on top of it would read as a crash.
            raise SystemExit(1)
        # **The verdict carries what it did NOT judge**, because the sentence
        # before it did not: an instance whose mail another product sends and
        # whose org policy somebody rewrote used to read "Zitadel agrees with
        # every row. Nothing changed." A reader who gets only the last line now
        # gets the count of surfaces nobody states an intent for and how many of
        # them belong to somebody else. The leading clause is unchanged on
        # purpose — it is what several tests and at least one deploy step read.
        self.stdout.write(
            self.style.SUCCESS(
                "Zitadel agrees with every row. "
                f"{report.observed} surface(s) observed, not judged; {report.foreign} foreign."
            )
        )


def read_report(*, tenant_slug: str) -> Report:
    """Every comparison, once. The lines, the count, and what would close each.

    **The one read both commands make.** `zitadel_audit` prints what comes back;
    `manage.py zitadel_reconcile` prints it and then asks for the repairs the
    findings name. Splitting the read in two — one walk for the report, another
    for the deltas — is how the two would come to disagree about an instance
    neither of them changed, and a tripwire that disagrees with the repairer is
    worse than either alone.

    Every call it makes is still a `GET` or a `_search`: the change-nothing
    property is this module's oldest and it is unchanged by who is reading.
    """
    lines: list[str] = []
    findings: list[Finding] = []
    drift = 0

    org = zitadel.organization()
    lines.append(f"instance        {org.get('name', '?')} ({org.get('id', '?')})")

    providers = zitadel.identity_providers()
    lines.append(f"idps in zitadel {len(providers)}")
    lines.append("")

    # Every tenant's realm first: a connection's provider lives in its tenant's
    # realm, so a missing realm explains the connection lines below it.
    homes = realms_section(tenant_slug=tenant_slug)
    lines.extend(homes.lines)
    drift += homes.drift
    findings.extend(homes.findings)

    connections = connections_section(tenant_slug=tenant_slug, providers=providers)
    lines.extend(connections.lines)
    drift += connections.drift
    findings.extend(connections.findings)

    # The workforce door, which has no row to walk and so was invisible to
    # everything above. It goes before the unclaimed count so that the
    # provider it claims is not also reported as a stranger.
    workforce = workforce_section(providers)
    lines.extend(workforce.lines)
    drift += workforce.drift
    findings.extend(workforce.findings)

    claimed = claimed_idp_ids(tenant_slug=tenant_slug)
    ours = workforce_provider(providers)
    if ours is not None:
        claimed.add(str(ours.get("id", "")))
    lines.extend(strangers_section(providers, claimed=claimed).lines)

    # The sign-in screen's look. Unlike the observed surfaces below it, this one
    # HAS an intent row, so it can reach a verdict and does.
    branding = branding_section()
    lines.extend(branding.lines)
    drift += branding.drift
    findings.extend(branding.findings)

    # The deployment's sign-in posture. Three more surfaces that graduated
    # out of the observed section — not because a row appeared, but because
    # the ENVIRONMENT is a sufficient intent (ADR ident-8), exactly as it
    # already was for the workforce door above.
    posture = posture_section()
    lines.extend(posture.lines)
    drift += posture.drift
    findings.extend(posture.findings)

    # The deployment's own project and applications — the one surface this
    # report's blind-spot paragraph used to admit it could not see. Judged
    # against settings, exactly as the workforce door and the posture are.
    applications = applications_section()
    lines.extend(applications.lines)
    drift += applications.drift
    findings.extend(applications.findings)

    # The manager role the login-v2 finalize needs. It is about the CREDENTIAL
    # rather than about any object, which is why it is its own section and its
    # own kind — and it is judged on every deployment, whichever sign-in page
    # this one serves, because the role costs a hosted-page deployment nothing
    # and its absence is what makes flipping the door a two-step move.
    login_client = login_client_section()
    lines.extend(login_client.lines)
    drift += login_client.drift
    findings.extend(login_client.findings)

    # The surfaces with no intent behind them at all. They add nothing to
    # `drift` and they are the last thing before the blind-spot paragraph,
    # because what they narrow is exactly what that paragraph declares. The
    # org's name is passed down rather than re-read: this report already
    # printed it at the top, and a second GET could disagree with the first.
    console = console_section(
        org_name=str(org.get("name", "?")),
        homed=sum(1 for one in homes.findings if one.verdict == AGREES),
        tenants=len(homes.findings),
    )
    lines.extend(console.lines)
    findings.extend(console.findings)

    return Report(lines=lines, drift=drift, findings=tuple(findings))


def realms_section(*, tenant_slug: str) -> Section:
    """Every tenant's realm — made, granted, and there — read through the realm port.

    One finding per tenant, and the population is the tenants themselves: a
    tenant with no home, a `pending` home, a realm the platform no longer has
    (a removed organisation reads as none — `zitadel.ORG_STATE_ACTIVE`) and a
    realm the platform's project is not granted to are each a DRIFT the
    reconciler repairs by asking for the tenant's home again; a realm that is
    all three is `agrees`. The count of those is the orgs line's `n of n
    tenants homed`.
    """
    lines: list[str] = [""]
    findings: list[Finding] = []
    drift = 0
    tenants = Tenant.objects.order_by("slug")
    if tenant_slug:
        tenants = tenants.filter(slug=tenant_slug)
    port = realms.current()
    for tenant in tenants:
        home = IdentityHome.objects.for_tenant(tenant).first()
        realm = get_tenant_realm(tenant)
        if realm is None:
            said = "has no home" if home is None else "is pending — its realm is not made yet"
            line = f"DRIFT       realm {tenant.slug} — {said}; its people cannot sign in"
        else:
            facts = port.facts(realm=realm)
            if not facts.exists:
                line = f"DRIFT       realm {tenant.slug} — org {realm.id} is gone at the platform"
            elif not facts.granted:
                line = (
                    f"DRIFT       realm {tenant.slug} — org {realm.id} is not granted the project"
                )
            else:
                line = f"agrees      realm {tenant.slug} — org {realm.id}, granted"
                lines.append(line)
                findings.append(Finding(AGREES, IDENTITY_HOME_KIND, tenant.slug, line))
                continue
        lines.append(line)
        findings.append(Finding(DRIFT, IDENTITY_HOME_KIND, tenant.slug, line))
        drift += 1
    return Section(lines=lines, drift=drift, findings=tuple(findings))


def enforced_line(connection: SsoConnection) -> Finding | None:
    """Whether the tenant realm's login policy says what the connection's `enforced` says.

    `None` for a connection with nothing to compare — not enforcing, and its
    realm's policy not requiring a provider either. Otherwise the realm is read
    through the port: enforcing means the password off, the provider required
    and THIS provider linked; anything else is drift the configuration sync
    repairs.
    """
    realm = get_tenant_realm(connection.tenant)
    if realm is None:
        return None
    facts = realms.current().facts(realm=realm)
    policy = facts.policy or LoginPolicy(password_allowed=True, provider_required=False)
    linked = connection.zitadel_idp_id in {one.id for one in facts.providers}
    label = f"{connection.tenant.slug}/{connection.name}"
    said = f"org {realm.id} policy allowUsernamePassword={str(policy.password_allowed).lower()}"
    if policy.provider_required:
        said += " allowExternalIdp=true"
    wanted = connection.enforced and connection.is_active
    if not wanted and not policy.provider_required:
        return None
    if wanted == (policy.provider_required and linked):
        return Finding(
            AGREES,
            KIND_SSO_CONNECTION,
            str(connection.pk),
            f"agrees      enforced — {said} ({label})",
        )
    return Finding(
        DRIFT,
        KIND_SSO_CONNECTION,
        str(connection.pk),
        f"DRIFT       enforced — our row says {'on' if wanted else 'off'}, {said} ({label})"
        f"{'' if linked or not wanted else ', provider not linked'}",
    )


def claimed_idp_ids(*, tenant_slug: str) -> set[str]:
    """Which Zitadel IdPs our own rows say they own. A database read, and only that.

    Separate from the walk that prints them because the stranger count needs it
    *after* the workforce section has had its say, and because it is the one
    part of that walk which touches nothing but our own tables — so re-deriving
    it costs a query and never a second question to Zitadel.
    """
    rows = SsoConnection.objects.filter(sync_state=SsoConnection.SyncState.APPLIED)
    if tenant_slug:
        rows = rows.filter(tenant__slug=tenant_slug)
    return {str(one) for one in rows.values_list("zitadel_idp_id", flat=True) if one}


def strangers_section(providers: list[dict[str, Any]], *, claimed: set[str]) -> Section:
    """IdPs Zitadel holds that no row of ours names.

    The one thing the row-by-row walk structurally cannot see. Counted rather
    than called drift, because a deployment may legitimately carry providers
    this product did not create — and a count is what makes a person go and
    look. No finding: there is nothing to repair, and deleting somebody else's
    provider is the move the ownership table says this product never makes.
    """
    unclaimed = [row for row in providers if str(row.get("id", "")) not in claimed]
    if not unclaimed:
        return Section(lines=[], drift=0)
    return Section(
        lines=[
            "",
            f"unclaimed   {len(unclaimed)} idp(s) in Zitadel that no row of ours names: "
            + ", ".join(sorted(str(row.get("name", "?")) for row in unclaimed)),
        ],
        drift=0,
    )


def connections_section(*, tenant_slug: str, providers: list[dict[str, Any]]) -> Section:
    """Every customer `SsoConnection`, compared against the IdP its row names."""
    by_id = {str(row.get("id", "")): row for row in providers}
    lines: list[str] = []
    findings: list[Finding] = []
    drift = 0

    rows = SsoConnection.objects.select_related("tenant").order_by("tenant__slug", "name")
    if tenant_slug:
        rows = rows.filter(tenant__slug=tenant_slug)

    for connection in rows:
        label = f"{connection.tenant.slug}/{connection.name}"
        key = str(connection.pk)
        state = connection.sync_state
        if state == SsoConnection.SyncState.UNMANAGED:
            lines.append(f"unmanaged   {label} — no sync has ever been asked for")
            continue
        if state == SsoConnection.SyncState.PENDING:
            # Not drift: the run may still be in flight. Reported anyway,
            # because a row that has been `pending` since last Tuesday is
            # the most interesting line in this report.
            lines.append(f"pending     {label} — sync started, not yet applied")
            continue
        if not connection.zitadel_idp_id:
            line = f"DRIFT       {label} — {state} but no Zitadel id recorded"
            lines.append(line)
            findings.append(Finding(DRIFT, KIND_SSO_CONNECTION, key, line))
            drift += 1
            continue

        remote = by_id.get(connection.zitadel_idp_id)
        realm = get_tenant_realm(connection.tenant)
        if remote is None and realm is not None:
            # A tenant's provider lives in its realm, invisible from the staff
            # org's list — read by id there.
            remote = zitadel.get_identity_provider(
                idp_id=connection.zitadel_idp_id, org_id=realm.id
            )
        if remote is None:
            remote = zitadel.get_identity_provider(idp_id=connection.zitadel_idp_id)
        if remote is None:
            line = (
                f"DRIFT       {label} — names idp {connection.zitadel_idp_id}, "
                "which Zitadel does not have"
            )
            lines.append(line)
            findings.append(Finding(DRIFT, KIND_SSO_CONNECTION, key, line))
            drift += 1
            continue

        expected = connection.idp_name
        actual = str(remote.get("name", ""))
        if actual != expected:
            line = f"DRIFT       {label} — idp is named {actual!r}, our row expects {expected!r}"
            lines.append(line)
            findings.append(Finding(DRIFT, KIND_SSO_CONNECTION, key, line))
            drift += 1
            continue

        remote_issuer = zitadel.oidc_issuer_of(remote)
        if remote_issuer and remote_issuer != connection.issuer:
            line = (
                f"DRIFT       {label} — idp issuer is {remote_issuer!r}, our row "
                f"says {connection.issuer!r}"
            )
            lines.append(line)
            findings.append(Finding(DRIFT, KIND_SSO_CONNECTION, key, line))
            drift += 1
            continue

        line = f"agrees      {label} — idp {connection.zitadel_idp_id}"
        lines.append(line)
        findings.append(Finding(AGREES, KIND_SSO_CONNECTION, key, line))
        enforced = enforced_line(connection)
        if enforced is not None:
            lines.append(enforced.line)
            findings.append(enforced)
            drift += enforced.verdict == DRIFT

    return Section(lines=lines, drift=drift, findings=tuple(findings))


def branding_section() -> Section:
    """The hosted sign-in screen, compared against the row that states its intent.

    **This surface changed class the day it got an intent row.**
    Before it there was no `IdentityBranding` row, so the label policy sat
    with the login policy and the SMTP sender in the observed-never-judged
    section: printed, because a person should see it, and unjudged, because
    a drift verdict needs an intent to disagree with and there was none.
    There is one now, so somebody repainting the login screen in the console
    — the exact move rule 27 says no check can see — is reported as drift by
    this clause.

    **Three states, and they are different facts.** No active row means
    nobody has ever stated an intent: the screen is whatever the console
    says, which is not drift, it is unmanaged — the same distinction
    `SyncState.UNMANAGED` draws for a connection nobody ever synced. An
    unreadable surface means we could not look, which is not the same as
    agreement and is not counted as drift either, because a report that
    called a network blip a console edit would send somebody hunting for a
    change nobody made. Only a readable policy that disagrees with a live
    row is drift.

    **The comparison is on the fields we state**, never on the whole object:
    Zitadel's policy carries `themeMode`, a `details` block and both `*Dark`
    twins whether or not our row has an opinion about them, and demanding
    equality over fields we never set would report drift on every deployment
    forever. A blank column means "we have no opinion", so it is skipped.
    """
    branding = IdentityBranding.objects.filter(is_active=True).first()
    lines: list[str] = [""]
    if branding is None:
        lines.append(
            "unmanaged   sign-in branding — no row states an intent, so the hosted "
            "screen is whatever the console says (set one: `set_identity_branding`)"
        )
        return Section(lines=lines, drift=0)

    key = str(branding.pk)
    try:
        policy = zitadel.label_policy()
    except zitadel.ZitadelError as error:
        line = f"could not    sign-in branding — {error}"
        lines.append(line)
        return Section(
            lines=lines,
            drift=0,
            findings=(Finding(UNREADABLE, KIND_IDENTITY_BRANDING, key, line),),
        )

    if policy.pop("_isInstanceDefault", False):
        line = (
            f"DRIFT       sign-in branding — a row states {branding.accent} and this org "
            "has NO label policy of its own; the screen is the instance default"
        )
        lines.append(line)
        return Section(
            lines=lines, drift=1, findings=(Finding(DRIFT, KIND_IDENTITY_BRANDING, key, line),)
        )

    disagreements = [
        f"{zitadel_key}: row says {ours!r}, Zitadel says {str(policy.get(zitadel_key, ''))!r}"
        for column, zitadel_key in zitadel.LABEL_POLICY_COLORS.items()
        for ours in [str(getattr(branding, column, "") or "")]
        if ours and str(policy.get(zitadel_key, "")) != ours
    ]
    if bool(policy.get("disableWatermark", False)) is not branding.is_watermark_disabled:
        disagreements.append(
            f"disableWatermark: row says {branding.is_watermark_disabled}, "
            f"Zitadel says {bool(policy.get('disableWatermark', False))}"
        )
    if disagreements:
        line = "DRIFT       sign-in branding — " + "; ".join(disagreements)
        lines.append(line)
        return Section(
            lines=lines, drift=1, findings=(Finding(DRIFT, KIND_IDENTITY_BRANDING, key, line),)
        )

    line = f"agrees      sign-in branding — accent {branding.accent}"
    lines.append(line)
    return Section(
        lines=lines, drift=0, findings=(Finding(AGREES, KIND_IDENTITY_BRANDING, key, line),)
    )


def posture_section() -> Section:
    """The deployment's sign-in posture, compared against the environment.

    **Three surfaces that moved from observed to reconciled**
    (ADR ident-8). Until this section, the instance's login policy, its
    lockout policy and its restrictions had no intent to disagree with, so
    they sat with the org's login policy and the SMTP sender: printed at
    best, and in the case of the lockout policy and the restrictions not
    even that. What changed is not that a row appeared — it is that the
    ENVIRONMENT is a sufficient intent for a comparison, which is what
    `_report_workforce` above has always done.

    **The instance's login policy AND the org's own, which are two doors.**
    The instance's governs every organisation that has not set one of its
    own — so it is the value that decides whether an org created tomorrow
    can register its own users. An org that HAS its own policy is governed
    by that one instead, and until the seed grew a writer for it there was
    nothing to compare it against: an operator turning this org's
    `allowRegister` back on in the console reopened the hosted registration
    page and this report said nothing, which is the blind spot the seed's
    `_org_posture` and this comparison close together.

    **Judged only where the org has a policy of its own.** An org that
    inherits is governed by the instance policy the section already judged,
    and reaching a second verdict on the same value would count one
    disagreement twice. So the inheriting case prints one line saying which
    verdict governs it and adds nothing to the count — the same shape
    "could not look" has, and for the same reason: a number a reader acts
    on has to mean one thing.

    The observed section below still prints the org policy's OTHER fields —
    its lifetimes, its factors, whose policy it is — still unjudged, because
    `allowRegister` is the only field of it this deployment states an intent
    for.

    **Could-not-look is not drift.** An unreadable surface says so and adds
    nothing to the count, for the reason `_report_branding` gives: a report
    that called a network blip a console edit would send somebody hunting
    for a change nobody made.
    """
    lines: list[str] = [""]
    findings: list[Finding] = []
    drift = 0

    def compare(label: str, *, expected: object, actual: object) -> None:
        nonlocal drift
        one_drift, line, verdict = _posture_line(label, expected=expected, actual=actual)
        drift += one_drift
        lines.append(line)
        findings.append(Finding(verdict, POSTURE_KIND, label, line))

    def unreadable(label: str, why: str) -> None:
        line = f"could not   posture {label} — {why}"
        lines.append(line)
        findings.append(Finding(UNREADABLE, POSTURE_KIND, label, line))

    try:
        login = zitadel.instance_login_policy()
    except zitadel.ZitadelError as error:
        unreadable("self-registration", str(error))
    else:
        compare(
            "self-registration",
            expected=bool(getattr(settings, "ZITADEL_ALLOW_SELF_REGISTRATION", False)),
            actual=bool(login.get("allowRegister", False)),
        )

    try:
        lockout = zitadel.lockout_policy()
    except zitadel.ZitadelError as error:
        unreadable("password lockout", str(error))
    else:
        compare(
            "password lockout",
            expected=int(getattr(settings, "ZITADEL_MAX_PASSWORD_ATTEMPTS", 0)),
            actual=int(lockout.get("maxPasswordAttempts", 0) or 0),
        )

    try:
        limits = zitadel.restrictions()
    except zitadel.ZitadelError as error:
        unreadable("public org registration", str(error))
    else:
        compare(
            "public org registration",
            # The setting is spelled ALLOW and the API field DISALLOW, so the
            # comparison flips here — once, at the edge, the same place every
            # other name Zitadel uses is translated. **The flip is on the
            # ANSWER, not on the expectation**, so both sides of the comparison
            # — and therefore the value printed — are in the label's own ALLOW
            # polarity. It was on the expectation once, and the line then read
            # `public org registration — True` over a door that was shut, beside
            # two siblings reading `False` and meaning the same thing.
            expected=bool(getattr(settings, "ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION", False)),
            actual=not bool(limits.get("disallowPublicOrgRegistration", False)),
        )

    try:
        org_login = zitadel.login_policy()
    except zitadel.ZitadelError as error:
        unreadable("org self-registration", str(error))
    else:
        if not org_login:
            unreadable("org self-registration", "the answer carried no policy")
        elif org_login.get("isDefault"):
            # Deliberately NOT the word "observed": the observed section
            # below is found by its heading, and a second line opening with
            # that word further up would make every reader of this report —
            # a person or a test — start the section in the wrong place.
            lines.append(
                "inherits    posture org login policy inherits the instance (judged above)"
            )
        else:
            compare(
                "org self-registration",
                expected=bool(getattr(settings, "ZITADEL_ALLOW_SELF_REGISTRATION", False)),
                actual=bool(org_login.get("allowRegister", False)),
            )

    return Section(lines=lines, drift=drift, findings=tuple(findings))


def _posture_line(label: str, *, expected: object, actual: object) -> tuple[int, str, str]:
    """One posture comparison. Returns (disagreements, the line, the verdict).

    Written out rather than folded into a loop over `(read, expected,
    actual)` triples because each of the three reads a different shape off a
    different endpoint, and a table of lambdas would be three coercions
    hidden behind one line — the readable half of a tripwire is that a
    person can see exactly what it compared.

    **It prints what it compared, and that is the whole of the discipline.** Any
    translation between Zitadel's spelling and ours belongs at the call site,
    on the ANSWER, so that the label, the expectation and the printed value are
    all in one polarity by the time they reach this function. A line that
    printed a flipped value under an unflipped label read as its own opposite.
    """
    if actual != expected:
        return (
            1,
            f"DRIFT       posture {label} — this deployment is configured for "
            f"{expected!r}, Zitadel says {actual!r}; run manage.py zitadel_seed",
            DRIFT,
        )
    return 0, f"agrees      posture {label} — {actual!r}", AGREES


def console_section(*, org_name: str, homed: int = 0, tenants: int = 0) -> Section:
    """The console's own surfaces: printed, and deliberately **not judged**.

    **Why observed rather than reconciled.** Every other line in this report
    starts from an intent — a `SsoConnection` row, or the environment the
    workforce door is switched by. What is left here has none: the org login
    policy's fields OTHER than `allowRegister` (its lifetimes, its factors,
    whose policy it is — the posture section judges the one field this
    deployment states an intent for and no more), the instance's SMTP
    sender, and how many organisations this instance holds. No product
    manages any of them through services, so there is nothing to disagree
    with. Reaching a drift VERDICT on them would mean inventing an intent
    row first, which is rule 27's whole materialisation machinery built to
    guard a surface nothing writes. The ADR names the trigger that would
    change that (ADR ident-2's amendment: the first product managing login
    policy or SMTP through services). Until then the honest report is the
    value and who owns it.

    **The organisation count is here because a thing nobody can count is a
    thing nobody notices arriving.** It was in the does-not-cover paragraph
    as "still invisible: a second organisation", and an instance that grew
    one would have looked exactly like an instance that had not. Counted,
    never inspected and never judged: what a second org's own policies say
    is a question for a product that has two, and the read that answers it
    is not this one.

    **So this section cannot change the exit status**, and that is the
    property, not a promise: it returns nothing, and `_report`'s caller adds
    nothing from it to `drift`. A reader who has automated on `zitadel_audit`
    exiting 0 sees new lines and the same exit.

    **And it cannot change Zitadel either.** Both calls are GETs
    (`apps/accounts/zitadel.py`, "the console's own surfaces"), so the
    mutate-then-assert-byte-identical discipline the rest of the audit is
    held to covers these unchanged.

    **Failure is a sentence, not an exception.** An unreadable surface says
    it could not look, because "could not look" and "nothing there" are
    different facts and the second one is what a person would wrongly read
    off a missing line.
    """
    lines: list[str] = [""]
    findings: list[Finding] = []
    lines.append(
        "observed    the console's own surfaces — printed, not judged; nothing "
        "states an intent for these, so none of them can be drift"
    )

    def observed(label: str, body: str, *, verdict: str = OBSERVED) -> None:
        line = f"  {label} {body}"
        lines.append(line)
        findings.append(Finding(verdict, "", label.strip(), line))

    try:
        policy = zitadel.login_policy()
    except zitadel.ZitadelError as error:
        observed("login-policy", f"could not be read — {error}")
    else:
        observed("login-policy", _login_policy_line(policy))

    try:
        smtp = zitadel.smtp_configuration()
    except zitadel.ZitadelError as error:
        observed("smtp        ", f"could not be read — {error}")
    else:
        owner = smtp_owner(smtp)
        observed(
            "smtp        ",
            _smtp_line(smtp),
            verdict=FOREIGN if zitadel.is_foreign(smtp) else OBSERVED,
        )
        if zitadel.is_foreign(smtp):
            # **A second line, not a longer one.** The observed line above says
            # what is configured; this one says what follows from it, and it is
            # the sentence somebody scanning for a left-hand keyword will find.
            # It is deliberately not the word DRIFT: there is no intent of ours
            # for a sender to disagree with (ADR ident-2 amended), so this is
            # not a disagreement — it is the fact that the mail Zitadel sends on
            # this deployment's behalf goes out as somebody else.
            lines.append(
                f"foreign      smtp — set by {owner}; Zitadel's OTP and reset mail from "
                f"this instance is sent as {smtp.get('senderAddress', '?')}; this "
                "deployment declares no SMTP intent (ADR ident-2 amended)"
            )

    try:
        orgs = zitadel.organizations()
    except zitadel.ZitadelError as error:
        observed("orgs        ", f"could not be read — {error}")
    else:
        observed("orgs        ", _orgs_line(orgs, owned=org_name, homed=homed, tenants=tenants))

    return Section(lines=lines, drift=0, findings=tuple(findings))


def smtp_owner(smtp: dict[str, Any]) -> str:
    """Who set this instance's SMTP sender, as far as its own description says.

    Zitadel's `description` is free text and is the only place an owner can be
    written down at all — there is no field for "which product configured
    this". This deployment's own seed writes `Set by <PRODUCT_NAME> (…)`, and
    the sibling product on the shared development instance writes the same
    shape, which is what makes the leading clause parseable rather than a
    guess. Anything else is `unknown`, and `unknown` is reported as the answer
    rather than smoothed into ours: "we do not know who set the sender every
    identity mail on this instance comes from" is the fact.
    """
    description = str(smtp.get("description", "") or "").strip()
    if not description:
        return "unknown"
    if description.lower().startswith("set by "):
        named = description[len("set by ") :].split("(")[0].strip()
        return named or "unknown"
    return description


def applications_section() -> Section:
    """The deployment's own project and applications, compared against settings.

    **The one surface this report's own blind-spot paragraph admitted to.** It
    said "any project or application no row of ours names" was invisible, and
    the deployment's OWN browser client is that: the object every person here
    signs in through. A one-field console edit to its redirect URI read as
    agreement, and the person signing in landed on raw HTTP 400 JSON at the
    identity platform — upstream of the callback, so no page of ours renders and
    no remedy is offered.

    **The intent is settings, and the road is the seed's writers.** There is no
    row: the project's name, the application names and the URIs are all derived
    from `config/settings` and the surfaces' base URLs, so this section compares
    against the same values `manage.py zitadel_seed` declares — imported from
    that command rather than restated, because a restatement here would be a
    second copy of the one thing the comparison is about.

    **What is judged, and what is only counted.** The browser client's
    `redirectUris`, `postLogoutRedirectUris` and `devMode` are judged, because
    those are the three the writer reconciles. The MCP resource and the MCP
    client are judged on EXISTENCE only: nothing reconciles their configuration
    yet, and reporting drift on a field with no road would be a finding an
    operator cannot act on.

    **Two projects bearing the declared name is drift that is NEVER repaired**
    (ADR platform-1). A changed `ZITADEL_PROJECT_NAME` makes a SECOND project,
    and a writer aimed at the wrong one of two same-named projects reconfigures
    a sibling deployment's sign-in. Both ids are printed and the reconciler
    refuses the kind; there is no safe automatic answer.
    """
    lines: list[str] = [""]
    declared_project = str(getattr(settings, "ZITADEL_PROJECT_NAME", "") or "")

    try:
        # The WHOLE search is kept, not only the rows that matched the declared
        # name. `_env_copies` below needs to tell "this id names nothing here"
        # from "this id names a project that is not ours", and that is the one
        # read that already knows — asking Zitadel a second time for a fact
        # this list holds would be a management call bought with nothing.
        every_project = list(zitadel.projects())
        candidates = [row for row in every_project if str(row.get("name", "")) == declared_project]
    except zitadel.ZitadelError as error:
        line = f"could not   applications — {error}"
        lines.append(line)
        return Section(
            lines=lines,
            drift=0,
            findings=(Finding(UNREADABLE, APPLICATIONS_KIND, "read", line),),
        )

    if not candidates:
        # **Two different facts, and the branding section draws the same line
        # for the same reason.** A deployment that has CONFIGURED sign-in —
        # `ZITADEL_CLIENT_ID` or an MCP audience in its environment — is a
        # deployment claiming a browser client, so a missing project means that
        # claim is false and nobody can sign in: drift, with the remedy. An
        # instance where nothing has been seeded and nothing claims it has is
        # not disagreeing with anything; it is UNMANAGED, which is the word this
        # report already uses for a surface no intent states — a fresh clone
        # before `scripts/setup.sh` runs, and every test world whose subject is
        # something else.
        if not _sign_in_is_configured():
            lines.append(
                f"unmanaged   applications — nothing is seeded on this instance and "
                f"nothing claims it is: no project named {declared_project!r}, and this "
                "checkout's environment names no client id and no MCP audience "
                "(seed it: `manage.py zitadel_seed`)"
            )
            return Section(lines=lines, drift=0)
        line = (
            f"DRIFT       applications — Zitadel holds no project named "
            f"{declared_project!r}, so this deployment has no browser client and "
            "nobody can sign in; run manage.py zitadel_seed"
        )
        lines.append(line)
        return Section(
            lines=lines,
            drift=1,
            findings=(Finding(DRIFT, APPLICATIONS_KIND, "missing", line),),
        )

    if len(candidates) > 1:
        ids = ", ".join(sorted(str(row.get("id", "?")) for row in candidates))
        line = (
            f"DRIFT       applications — {len(candidates)} projects named "
            f"{declared_project!r} ({ids}). A changed name is a SECOND object, never a "
            "rename (ADR platform-1), and nothing here will rename or delete either — "
            "point ZITADEL_PROJECT_NAME at the one this deployment owns"
        )
        lines.append(line)
        return Section(
            lines=lines,
            drift=1,
            findings=(Finding(DRIFT, APPLICATIONS_KIND, "ambiguous-project", line),),
        )

    project = candidates[0]
    project_id = str(project.get("id", ""))
    try:
        apps = zitadel.applications(project_id=project_id)
    except zitadel.ZitadelError as error:
        line = f"could not   applications — {error}"
        lines.append(line)
        return Section(
            lines=lines,
            drift=0,
            findings=(Finding(UNREADABLE, APPLICATIONS_KIND, "read", line),),
        )

    by_name = {str(row.get("name", "")): row for row in apps}
    findings: list[Finding] = []
    drift = 0

    expected_names = [
        str(getattr(settings, "ZITADEL_BROWSER_APP_NAME", "") or ""),
        str(getattr(settings, "ZITADEL_MCP_RESOURCE_NAME", "") or ""),
        str(getattr(settings, "ZITADEL_MCP_CLIENT_NAME", "") or ""),
    ]
    missing = [name for name in expected_names if name and name not in by_name]
    if missing:
        line = (
            f"DRIFT       applications — project {declared_project} ({project_id}) is "
            f"missing {', '.join(missing)}; run manage.py zitadel_seed"
        )
        lines.append(line)
        findings.append(Finding(DRIFT, APPLICATIONS_KIND, "missing", line))
        drift += 1

    browser = by_name.get(expected_names[0])
    if browser is not None:
        # The seed's own list — `core.surfaces.surface_base_urls`, one derivation
        # — so a second surface's callback is declared here exactly as it is
        # registered there, and never reads as drift the seed would re-write.
        bases = surface_base_urls()
        live = zitadel.oidc_app_config_of(browser)
        declared = {
            "redirectUris": [f"{base}{seed.BROWSER_CALLBACK_PATH}" for base in bases],
            "postLogoutRedirectUris": [f"{base}{seed.BROWSER_LOGOUT_PATH}" for base in bases],
            "devMode": bases[0].startswith("http://"),
        }
        disagreements = [
            f"{key}: live {live.get(key)!r}, declared {value!r}"
            for key, value in declared.items()
            if live.get(key) != value
        ]
        if disagreements:
            line = (
                f"DRIFT       applications — {expected_names[0]} "
                f"({browser.get('id', '?')}) " + "; ".join(disagreements)
            ) + "; run manage.py zitadel_seed"
            lines.append(line)
            findings.append(Finding(DRIFT, APPLICATIONS_KIND, "uris", line))
            drift += 1
        else:
            line = (
                f"agrees      applications — project {declared_project} ({project_id}), "
                f"{', '.join(name for name in expected_names if name in by_name)}"
            )
            lines.append(line)
            findings.append(Finding(AGREES, APPLICATIONS_KIND, "uris", line))

    version_lines, version_drift, version_findings = _login_versions(by_name=by_name)
    lines.extend(version_lines)
    drift += version_drift
    findings.extend(version_findings)

    env_lines, env_drift, env_findings = _env_copies(
        project_id=project_id,
        by_name=by_name,
        project_names_by_id={
            str(row.get("id", "")): str(row.get("name", ""))
            for row in every_project
            if str(row.get("id", ""))
        },
    )
    lines.extend(env_lines)
    drift += env_drift
    findings.extend(env_findings)

    return Section(lines=lines, drift=drift, findings=tuple(findings))


def _login_versions(*, by_name: dict[str, dict[str, Any]]) -> tuple[list[str], int, list[Finding]]:
    """Which login UI each OIDC client declares, against what we declare (C-9).

    **The half the applications section could not see, and the one that takes a
    deployment down hardest when it is wrong.** `loginVersion` decides where
    `GET /oauth/v2/authorize` sends a person before any page of ours renders:
    a v2 declaration nobody here made sends everybody to a URL this deployment
    does not serve, and clicking "sign in" then answers a 404 from our own host
    with no remedy on it. It is not a field the seed's URI writer touches —
    `ensure_web_application` carries it back byte-identical on purpose — so
    nothing noticed it until this line.

    **Both directions, because the reverse is the one that was missing.** The
    intent is `zitadel_seed.declared_login_base_uri`, today `None`; a live
    declaration where we declare none is drift with the same remedy as a
    missing one — run the seed, whose writer CLEARS. That reverse is what the
    consumer lacked when an owner spent a morning locked out.

    Judged on the whole `loginVersion` value rather than on the base URI,
    because `{"loginV2": {}}` and `{"loginV1": {}}` are both declarations this
    deployment did not make and neither carries a URI to compare.

    Only the two OIDC clients: the MCP *resource* is an API application with no
    OIDC config at all, and reporting a login version on an object nobody logs
    in through would be a finding nobody can act on.
    """
    base_url = surface_base_urls()[0]
    declared = zitadel.login_version_declaration(seed.declared_login_base_uri(base_url))
    stated = _login_version_words(declared)

    lines: list[str] = []
    findings: list[Finding] = []
    drift = 0
    judged: list[str] = []
    for name in (
        str(getattr(settings, "ZITADEL_BROWSER_APP_NAME", "") or ""),
        str(getattr(settings, "ZITADEL_MCP_CLIENT_NAME", "") or ""),
    ):
        application = by_name.get(name)
        if not name or application is None:
            continue
        live = zitadel.login_version_of(application)
        if live == declared:
            judged.append(name)
            continue
        line = (
            f"DRIFT       applications — {name} ({application.get('id', '?')}) "
            f"loginVersion: live {_login_version_words(live)}, declared {stated}. That is "
            "where GET /oauth/v2/authorize sends a person before any page of ours "
            "renders; run manage.py zitadel_seed"
        )
        lines.append(line)
        findings.append(Finding(DRIFT, APPLICATIONS_KIND, "login-version", line))
        drift += 1

    if judged:
        line = f"agrees      applications — loginVersion {stated}: {', '.join(judged)}"
        lines.append(line)
        findings.append(Finding(AGREES, APPLICATIONS_KIND, "login-version", line))
    return lines, drift, findings


def _login_version_words(version: dict[str, Any] | None) -> str:
    """One `loginVersion` value as a sentence fragment a reader can act on.

    The raw protobuf shape is unreadable in a terminal column and its ABSENCE
    is the state this deployment declares, which `None` renders as nothing at
    all — so a line comparing two of them would read "live , declared ".
    """
    if not version:
        return "none (the identity platform's own page)"
    two = version.get("loginV2")
    if isinstance(two, dict):
        uri = str(two.get("baseUri", ""))
        return f"v2 at {uri}" if uri else "v2 at the instance's own URI"
    if "loginV1" in version:
        return "v1 pinned"
    return f"an unknown declaration {version!r}"


def login_client_section() -> Section:
    """Whether the machine credential may finalize a login-v2 sign-in (M2).

    **A permission, judged like an object, because its absence looks like an
    outage.** `POST /v2/oidc/auth_requests/{id}` is the call that turns a
    signed-in session into the OIDC code the relying party is waiting for, and
    it answers `403 AUTH-AWfge` for a machine user holding `IAM_OWNER` and not
    `IAM_LOGIN_CLIENT`. Nothing else in a deployment behaves differently: every
    seed, every audit and every sync keeps working, and sign-in fails at the
    last hop with a refusal that names no role. The consumer's whole rung for
    the front door was BLOCKED on it (design I-A, fact 2), and a fact that
    expensive is not one to leave to a runbook step.

    **Judged on a deployment that has not flipped the door yet, deliberately.**
    The role costs a deployment on the hosted page nothing — it authorises a
    call that deployment never makes — and having it already true is what keeps
    `SIGN_IN_DOOR=ours` a setting flip rather than a setting flip plus a
    console visit. So the intent is "always held", and an instance without it
    is drift whichever page this deployment serves.

    Its road is the seed's writer (`ensure_instance_member_role`), which is why
    the finding carries its own kind rather than the applications': the
    reconciler runs the same command for both and the flag that selects one
    should not silently select the other.
    """
    lines: list[str] = [""]
    try:
        user = zitadel.machine_user()
        user_id = str(user.get("id", ""))
        roles = zitadel.instance_member_roles(user_id=user_id) if user_id else []
    except zitadel.ZitadelError as error:
        line = f"could not   login client — {error}"
        lines.append(line)
        return Section(
            lines=lines,
            drift=0,
            findings=(Finding(UNREADABLE, LOGIN_CLIENT_KIND, "roles", line),),
        )

    who = str(user.get("preferredLoginName", "") or user.get("userName", "?"))
    if zitadel.LOGIN_CLIENT_ROLE in roles:
        line = (
            f"agrees      login client — {who} holds {zitadel.LOGIN_CLIENT_ROLE} "
            f"({', '.join(sorted(roles))})"
        )
        lines.append(line)
        return Section(
            lines=lines, drift=0, findings=(Finding(AGREES, LOGIN_CLIENT_KIND, "roles", line),)
        )

    line = (
        f"DRIFT       login client — {who} does not hold {zitadel.LOGIN_CLIENT_ROLE} "
        f"({', '.join(sorted(roles)) or 'no instance role at all'}), so the login-v2 "
        "finalize POST /v2/oidc/auth_requests/<id> answers 403 AUTH-AWfge and nobody "
        "completes a sign-in on our own page; IAM_OWNER does not carry it. Run "
        "manage.py zitadel_seed"
    )
    lines.append(line)
    return Section(
        lines=lines, drift=1, findings=(Finding(DRIFT, LOGIN_CLIENT_KIND, "roles", line),)
    )


def _sign_in_is_configured() -> bool:
    """Whether this checkout's environment CLAIMS a browser client or an MCP door.

    The claim is what makes an absence a disagreement. `ZITADEL_CLIENT_ID` is
    how the relying party names the application at all, and an MCP audience is
    what the resource server checks a token's `aud` against — either one set is
    a deployment saying "those objects exist and I use them". Neither set is a
    checkout that has not been configured, and on that checkout a missing
    project is news rather than drift.

    Deliberately NOT the PAT or the issuer: those are set on every checkout that
    can talk to Zitadel at all, including the rung worktrees on this machine,
    and reading them as a claim would make every one of them read as a broken
    deployment.
    """
    if str(getattr(settings, "ZITADEL_CLIENT_ID", "") or "").strip():
        return True
    return any(str(one).strip() for one in (getattr(settings, "ZITADEL_MCP_AUDIENCE", []) or []))


def _stranger_clause(one: str, project_names_by_id: dict[str, str]) -> str:
    """What an audience id that is not one of the two legal values actually is.

    **Two different facts, and the report used to print one of them over both.**
    An id the instance has never heard of is a dead pointer — a re-seeded
    checkout keeping the previous project's id, the case `_env_copies` below
    describes. An id that RESOLVES, to a project this same search already
    listed, is a live pointer aimed at somebody else: a sibling deployment on a
    shared instance, or the same product's other project. Both refuse every
    token, so both are drift; they are not the same thing to go and fix, and
    "names nothing on this instance" told an operator to look for an object
    that was sitting in the console the whole time. Found LIVE, not imagined:
    a deployment's `ZITADEL_MCP_AUDIENCE` named a NEIGHBOURING project on the
    shared instance, the audit called it nothing, and the MCP door refused
    every token while the id it wanted was two rows down the console list.

    **It costs no call.** The names come from the projects search
    `applications_section` already performed; this asks Zitadel nothing, which
    is what keeps the read-only property (`zitadel.projects()` is the same GET
    either way) and the one-read discipline the reconciler depends on.
    """
    name = project_names_by_id.get(one)
    if name:
        return (
            f"{one} names project {name} ({one}) on this instance, which is not this deployment's"
        )
    return f"{one} names nothing on this instance"


def _env_copies(
    *,
    project_id: str,
    by_name: dict[str, dict[str, Any]],
    project_names_by_id: dict[str, str],
) -> tuple[list[str], int, list[Finding]]:
    """`.env`'s copies of two values Zitadel minted, beside the live ones.

    **Two facts Zitadel owns and this deployment has to keep a copy of.** The
    browser client's id is minted at creation and the RP cannot name it any
    other way; the MCP audience is what an access token's `aud` has to carry and
    the resource server cannot check it without one. Both copies live in `.env`,
    and **nothing here repairs them**: a command that edited the operator's
    environment file would be writing the one artifact they own outright. So the
    honest report is both values side by side, drift on a difference, and the
    remedy in words.

    **Unset is not a difference.** A checkout with no browser sign-in
    configured — every rung worktree on this machine — must not read as a broken
    deployment, so an empty copy is printed as `unset` and moves nothing. The
    audience is the sharper case: `scripts/setup.sh` writes it only when the
    slot is EMPTY, so a checkout whose project was recreated silently keeps the
    previous project's id and the MCP door then refuses every token, because the
    `aud` it demands names nothing.

    **Either of two live values satisfies the audience**, which is measured and
    not a leniency: Zitadel puts both the project id and the API application's
    client id in `aud` (`.env.example` says so), so a census accepting only one
    of them would call a working deployment drift.
    """
    lines: list[str] = []
    findings: list[Finding] = []
    drift = 0

    browser_name = str(getattr(settings, "ZITADEL_BROWSER_APP_NAME", "") or "")
    live_client = str(
        ((by_name.get(browser_name) or {}).get("oidcConfig") or {}).get("clientId", "")
    )
    env_client = str(getattr(settings, "ZITADEL_CLIENT_ID", "") or "").strip()
    tail = f"live {live_client or 'none'}  env ZITADEL_CLIENT_ID {env_client or 'unset'}"
    if env_client and live_client and env_client != live_client:
        line = (
            f"DRIFT       client id   {browser_name}  {tail}; put the live id in .env "
            "(and --rotate-web-secret if the secret went with it)"
        )
        drift += 1
        findings.append(Finding(DRIFT, ENV_COPY_KIND, "client id", line))
    else:
        line = f"agrees      client id   {browser_name}  {tail}"
        findings.append(Finding(AGREES, ENV_COPY_KIND, "client id", line))
    lines.append(line)

    resource_name = str(getattr(settings, "ZITADEL_MCP_RESOURCE_NAME", "") or "")
    resource = by_name.get(resource_name) or {}
    resource_client = str((resource.get("apiConfig") or {}).get("clientId", ""))
    env_audience = [
        str(one).strip()
        for one in (getattr(settings, "ZITADEL_MCP_AUDIENCE", []) or [])
        if str(one).strip()
    ]
    legal = {one for one in (project_id, resource_client) if one}
    tail = (
        f"live project {project_id or 'none'} / resource {resource_client or 'none'}  "
        f"env ZITADEL_MCP_AUDIENCE {', '.join(env_audience) or 'unset'}"
    )
    strangers = [one for one in env_audience if one not in legal]
    if strangers:
        line = (
            f"DRIFT       audience    {resource_name}  {tail}; "
            f"{'; '.join(_stranger_clause(one, project_names_by_id) for one in strangers)}"
            " — the MCP door "
            "refuses every token until .env carries the live project id"
        )
        drift += 1
        findings.append(Finding(DRIFT, ENV_COPY_KIND, "audience", line))
    else:
        line = f"agrees      audience    {resource_name}  {tail}"
        findings.append(Finding(AGREES, ENV_COPY_KIND, "audience", line))
    lines.append(line)

    return lines, drift, findings


def _login_policy_line(policy: dict[str, Any]) -> str:
    """One line for the org's login policy, whose-is-it first.

    `isDefault` is the field that carries the news: Zitadel sends it when the
    org has no policy of its own and the instance default is answering, and
    omits it once somebody has set one. So "somebody changed this org's login
    policy" is readable off a single GET, and it is the first thing on the
    line because it is the only part a reader can act on.
    """
    if not policy:
        return "no policy in the answer"
    owner = (policy.get("details") or {}).get("resourceOwner", "?")
    whose = (
        "the instance default (no policy of this org's own)"
        if policy.get("isDefault")
        else "set on this org (not the instance default)"
    )
    switches = ", ".join(
        name
        for name, on in (
            ("username+password", policy.get("allowUsernamePassword")),
            ("self-registration", policy.get("allowRegister")),
            ("external idp", policy.get("allowExternalIdp")),
            ("domain discovery", policy.get("allowDomainDiscovery")),
            ("unknown usernames ignored", policy.get("ignoreUnknownUsernames")),
            ("phone login disabled", policy.get("disableLoginWithPhone")),
        )
        if on
    )
    factors = ", ".join(str(one) for one in (policy.get("secondFactors") or []))
    return (
        f"{whose}, resourceOwner {owner}; on: {switches or 'nothing'}; "
        f"passwordless {policy.get('passwordlessType', '?')}; "
        f"second factors {factors or 'none'}"
    )


def _orgs_line(orgs: list[dict[str, Any]], *, owned: str, homed: int = 0, tenants: int = 0) -> str:
    """How many organisations this instance holds, and which one is ours.

    The count first, because the count is the whole news: one is the shape
    every clone of this template is in, and anything else is a fact somebody
    should know before reading the rest of this report as if it covered the
    instance. The names follow so a reader can see WHICH other org appeared
    without going to the console, and they are truncated rather than paged —
    this line is a tripwire, not an inventory.
    """
    if not orgs:
        return "no organisations in the answer"
    names = [str(row.get("name", "?")) for row in orgs]
    shown = ", ".join(names[:5]) + (f", … (+{len(names) - 5})" if len(names) > 5 else "")
    return (
        f"{len(orgs)} on this instance (observed; the seed owns {owned}; "
        f"{homed} of {tenants} tenants homed) — {shown}"
    )


def _smtp_line(smtp: dict[str, Any]) -> str:
    """One line for the instance's SMTP sender, and **who owns it**.

    Instance-wide, so on a shared development instance this names whoever
    configured it last — which is the fact worth printing and the reason this
    read is here at all. **No credential is on this line**: the API does not
    return the SMTP password, so there is none to leak into a report somebody
    will paste into a ticket.

    **`owner:` is first among the trailing clauses.** The description was
    already printed, at the end, in quotes, as colour — and a report whose
    verdict then said "Zitadel agrees with every row" over another product's
    `Set by …` string had named the owner without noticing it. Principle 9 wants
    the owner of a duplicated or unowned fact stated, not merely visible, so it
    is parsed out and labelled, and `console_section` counts it.
    """
    if not smtp:
        return "no SMTP configuration on this instance"
    description = str(smtp.get("description", "") or "").strip()
    return (
        f"instance-wide — {smtp.get('senderName', '?')} "
        f"<{smtp.get('senderAddress', '?')}> via {smtp.get('host', '?')}, "
        f"{smtp.get('state', '?')}, id {smtp.get('id', '?')}"
        f"; owner: {smtp_owner(smtp)}" + (f"; described as {description!r}" if description else "")
    )


def blind_spot_lines() -> list[str]:
    """What a clean verdict does **not** cover, printed beside the verdict.

    This paragraph used to live in this module's docstring, where the person
    who most needs it — somebody reading a green report — never sees it. A
    blind spot declared only where the maintainer looks is a blind spot the
    operator does not have. So it prints, every run, both verdicts, in the
    one place a reader is already looking: immediately above the line that
    says whether the two agree.

    It is a function returning lines rather than a printer for the reason every
    section here is: `manage.py zitadel_reconcile` prints it too, and a repairer
    that suppressed the caveat would be the one place it matters most.
    """
    return [
        "does not cover",
        "  This compares what our ROWS declare, plus the workforce door and the",
        "  sign-in posture the environment declares — which now reaches one field of",
        "  THIS ORG's own login policy, `allowRegister`, where the org has a policy",
        "  of its own. Every other field of it is printed in the observed section",
        "  above and judged by nothing, as is the instance's SMTP sender: no intent",
        "  states them, so neither can disagree with anything and neither moves the",
        "  exit code — the sender's OWNER is named and counted beside the verdict,",
        "  which is a fact about it and still not a verdict on it. An org that",
        "  INHERITS is governed by the instance policy the posture section already",
        "  judged, and nothing here writes an org a policy it does not have.",
        "  Counted, not inspected: this instance's organisations — a second one is",
        "  visible in the observed section above and nothing reads its policies.",
        "  Still invisible: any instance-level policy beyond",
        "  the three the posture section names, actions,",
        "  machine keys, every instance manager role except the one the login-v2",
        "  finalize needs (the login client section judges that one and no other,",
        "  on the machine credential and on nobody else's account),",
        "  and any project or application NO SETTING of ours names —",
        "  the deployment's own project, its browser client, its MCP resource and",
        "  its MCP client are compared against settings in the applications section",
        "  above, and a project a sibling checkout made under another name is not.",
        "  The stranger IdPs are only counted, above, never inspected. So is anything",
        "  changed and changed back between two runs: this is a point-in-time read,",
        "  and running it again is the only diff there is.",
        "  House rule 27 fences this codebase. It cannot fence the console.",
    ]


def workforce_provider(providers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The Google IdP this deployment's own door would be, if Zitadel holds one.

    A pure `next(...)` over a list already fetched, so both the section below
    and `read_report`'s stranger count can ask without a second question to
    Zitadel — which is why the section can return the house `(lines, drift)`
    shape instead of smuggling an id out beside it.
    """
    name = zitadel.workforce_idp_name()
    return next((row for row in providers if str(row.get("name", "")) == name), None)


def workforce_section(providers: list[dict[str, Any]]) -> Section:
    """The deployment's own door.

    **Why this section exists.** Every other line in this report starts from
    a row. The workforce provider has none — its intent is the environment
    (`_apply_workforce_provider`: "nothing is written back, and that is the
    honest shape") — so the row-by-row walk could not see it, and the one
    door the people running this product sign in through was the one thing
    rule 27's blind spot covered completely.

    **What is compared.** `GOOGLE_WORKSPACE_DOMAINS` is the switch: empty is
    the door off, non-empty is the door on. Zitadel either holds a Google
    provider under our name or it does not. Both directions of that
    disagreement are drift, and each is its own sentence, because they are
    different incidents: one is staff who cannot sign in, the other is a
    live Google door onto a product that refuses everybody it sends.

    Then the client id, which is the console change our rows structurally
    cannot notice: a provider re-pointed at somebody else's Google project
    still has our name on it and would otherwise read as clean.

    **What is not compared, and why it cannot be.** The domain *list* is not
    in Zitadel at all, deliberately (ADR ident-6, `ensure_google_identity_
    provider`): `GOOGLE_WORKSPACE_DOMAINS` stays ours and is enforced by
    the platform door's workforce wall (`accounts.adapter`, a NEW person at
    sign-up, through `policies.is_workforce_email`), because a restriction
    expressed only in somebody else's console is a restriction we cannot
    test. So there is no per-domain set to diff — the report prints the list
    beside the provider and says where it is enforced, which is the true
    thing to print rather than a comparison against a field that does not
    exist.

    **Every line here carries the same `key`**, and there is only one thing it
    could be: the digest the service builds from the environment. The key is
    rebuilt by the service at ask time rather than carried from here, because
    the environment is the intent and this section is a reader of it.
    """
    name = zitadel.workforce_idp_name()
    domains = sorted(get_workforce_domains())
    provider = workforce_provider(providers)
    lines: list[str] = [""]

    if provider is None:
        if not domains:
            lines.append(
                f"workforce   off on both sides — GOOGLE_WORKSPACE_DOMAINS is empty "
                f"and Zitadel holds no provider named {name!r}"
            )
            return Section(lines=lines, drift=0)
        line = (
            f"DRIFT       workforce — GOOGLE_WORKSPACE_DOMAINS names "
            f"{', '.join(domains)}, but Zitadel holds no provider named {name!r}. "
            "Staff cannot sign in; run manage.py sync_workforce_idp."
            # This line used to name `zitadel_seed` and
            # `sync_workforce_identity_config`, and NEITHER is a way out of
            # this drift: `zitadel_seed` makes the project, the applications
            # and the dev user and has never touched a provider, and
            # `sync_workforce_identity_config` is the *service* — a name
            # with no command behind it, so an operator who pasted it got
            # "Unknown command". A remedy that does not work is worse than
            # none: it costs the reader the time to try it and then the
            # trust to believe the next one. `sync_workforce_idp` is the
            # command that exists, and it is the door onto that service.
        )
        lines.append(line)
        return Section(
            lines=lines, drift=1, findings=(Finding(DRIFT, KIND_WORKFORCE_PROVIDER, "", line),)
        )

    provider_id = str(provider.get("id", ""))
    if not domains:
        line = (
            f"DRIFT       workforce — GOOGLE_WORKSPACE_DOMAINS is empty, so this "
            f"deployment refuses every workforce address, but Zitadel still holds "
            f"a live provider named {name!r} (idp {provider_id})"
        )
        lines.append(line)
        return Section(
            lines=lines,
            drift=1,
            findings=(Finding(DRIFT, KIND_WORKFORCE_PROVIDER, provider_id, line),),
        )

    expected_client = str(getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or "").strip()
    actual_client = zitadel.google_client_id_of(provider)
    if expected_client and actual_client and actual_client != expected_client:
        line = (
            f"DRIFT       workforce — idp {provider_id} points at Google client "
            f"{actual_client!r}, this deployment is configured for "
            f"{expected_client!r}"
        )
        lines.append(line)
        return Section(
            lines=lines,
            drift=1,
            findings=(Finding(DRIFT, KIND_WORKFORCE_PROVIDER, provider_id, line),),
        )

    line = (
        f"agrees      workforce — idp {provider_id}, domains {', '.join(domains)} "
        "(enforced by this deployment's sign-in door at sign-up, not in Zitadel — ADR ident-6)"
    )
    lines.append(line)
    return Section(
        lines=lines,
        drift=0,
        findings=(Finding(AGREES, KIND_WORKFORCE_PROVIDER, provider_id, line),),
    )
