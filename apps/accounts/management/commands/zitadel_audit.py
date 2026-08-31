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
Repairing is deliberately not built (shop-the-price): an auto-repairing
reconciler guards drift nobody can cause yet, and its trigger is named in the
ADR — first observed drift, or first production deploy, whichever comes first.

**Two populations, not one.** Every customer `SsoConnection` is compared against
the IdP its row names — and then the **workforce** door is compared against the
environment, because it has no row to name anything with (`_report_workforce`).
Without that section, the one door the people running
this product sign in through was the one thing rule 27's blind spot covered
completely, since the row-by-row walk had nothing to start from.

**And a third section that reaches no verdict at all.** The org's login policy
and the instance's SMTP sender are *observed and printed*, never judged
(`_report_console`): no product manages either through services, so no intent
row exists to disagree with, and reaching a drift verdict on them would mean
inventing that machinery to guard a surface nothing writes. They are GETs like
everything else here, so the change-nothing property covers them unchanged, and
they add nothing to the exit status. ADR ident-2's amendment records the
decision and the trigger that would revisit it — the first product managing
login policy or SMTP through services.

**What it cannot see is now PRINTED beside the verdict** (`_report_blind_spot`),
rather than left in this docstring where only a maintainer would find it: it
compares what our rows *declare*, and a class of Zitadel configuration this
product never writes — a second organisation, an instance-level policy, an IdP
created by hand under a name no row claims — is invisible to it, except for the
one summary line counting IdPs Zitadel has that no row names. That is the
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

from typing import Any

from django.conf import settings
from django.core.management.base import CommandError

from apps.accounts import zitadel
from apps.accounts.models import SsoConnection
from apps.core.management import BaseCommand


# What an SSO connection is called inside Zitadel. The same derivation
# `apps/accounts/activities.py` uses, restated here rather than imported,
# because a command importing an activity would drag Temporal into a shell
# process for one f-string. `apps/accounts/tests/test_zitadel.py` pins
# the two against each other, so a change to one fails a test rather than
# silently making the audit compare the wrong names.
def idp_name_for(connection: SsoConnection) -> str:
    return f"{connection.tenant.slug}:{connection.pk}"


# The workforce provider's name, restated here for the same reason
# `idp_name_for` is: a command may not import an activity. It has no row at all
# — its intent is the environment — so this constant is the *only* handle either
# side has on it, which makes the restatement more load-bearing here than there.
# `test_zitadel_workforce_audit.py` pins the two together.
WORKFORCE_IDP_NAME = "Workforce Google"


def workforce_idp_name() -> str:
    return str(getattr(settings, "GOOGLE_WORKFORCE_IDP_NAME", WORKFORCE_IDP_NAME))


def workforce_domains() -> list[str]:
    """The domains this deployment's workforce door is configured for.

    **The switch, not a decoration.** Empty means the door is off entirely —
    `config/settings/base.py` and `services.sync_workforce_identity_config` both
    read it that way — which is what makes "empty here, a live provider there"
    a disagreement worth a line.
    """
    return [
        str(one).strip().lower()
        for one in (getattr(settings, "GOOGLE_WORKSPACE_DOMAINS", []) or [])
        if str(one).strip()
    ]


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
            drift = self._report(tenant_slug=str(options["tenant"]).strip().lower())
        except zitadel.ZitadelError as error:
            raise CommandError(str(error)) from error

        self.stdout.write("")
        self._report_blind_spot()
        self.stdout.write("")
        if drift:
            self.stdout.write(self.style.WARNING(f"{drift} disagreement(s). Nothing was changed."))
            # A non-zero exit so this can be a deploy step. `SystemExit` rather
            # than `CommandError`, because the report already said everything
            # and a traceback-shaped error on top of it would read as a crash.
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("Zitadel agrees with every row. Nothing changed."))

    def _report(self, *, tenant_slug: str) -> int:
        """Every comparison, printed. Returns how many disagreed."""
        org = zitadel.organization()
        self.stdout.write(f"instance        {org.get('name', '?')} ({org.get('id', '?')})")

        providers = zitadel.identity_providers()
        by_id = {str(row.get("id", "")): row for row in providers}
        self.stdout.write(f"idps in zitadel {len(providers)}")
        self.stdout.write("")

        rows = SsoConnection.objects.select_related("tenant").order_by("tenant__slug", "name")
        if tenant_slug:
            rows = rows.filter(tenant__slug=tenant_slug)

        drift = 0
        claimed: set[str] = set()
        for connection in rows:
            label = f"{connection.tenant.slug}/{connection.name}"
            state = connection.sync_state
            if state == SsoConnection.SyncState.UNMANAGED:
                self.stdout.write(f"unmanaged   {label} — no sync has ever been asked for")
                continue
            if state == SsoConnection.SyncState.PENDING:
                # Not drift: the run may still be in flight. Reported anyway,
                # because a row that has been `pending` since last Tuesday is
                # the most interesting line in this report.
                self.stdout.write(f"pending     {label} — sync started, not yet applied")
                continue
            if not connection.zitadel_idp_id:
                self.stdout.write(f"DRIFT       {label} — {state} but no Zitadel id recorded")
                drift += 1
                continue

            claimed.add(connection.zitadel_idp_id)
            remote = by_id.get(connection.zitadel_idp_id)
            if remote is None:
                remote = zitadel.get_identity_provider(idp_id=connection.zitadel_idp_id)
            if remote is None:
                self.stdout.write(
                    f"DRIFT       {label} — names idp {connection.zitadel_idp_id}, "
                    "which Zitadel does not have"
                )
                drift += 1
                continue

            expected = idp_name_for(connection)
            actual = str(remote.get("name", ""))
            if actual != expected:
                self.stdout.write(
                    f"DRIFT       {label} — idp is named {actual!r}, our row expects {expected!r}"
                )
                drift += 1
                continue

            remote_issuer = zitadel.oidc_issuer_of(remote)
            if remote_issuer and remote_issuer != connection.issuer:
                self.stdout.write(
                    f"DRIFT       {label} — idp issuer is {remote_issuer!r}, our row "
                    f"says {connection.issuer!r}"
                )
                drift += 1
                continue

            self.stdout.write(f"agrees      {label} — idp {connection.zitadel_idp_id}")

        # The workforce door, which has no row to walk and so was invisible to
        # everything above. It goes before the unclaimed count so that the
        # provider it claims is not also reported as a stranger.
        workforce_drift, workforce_id = self._report_workforce(providers)
        drift += workforce_drift
        if workforce_id:
            claimed.add(workforce_id)

        # The one thing the row-by-row walk structurally cannot see: an IdP that
        # exists in Zitadel and that no row of ours claims. Counted rather than
        # called drift, because a deployment may legitimately carry providers
        # this product did not create — and a count is what makes a person go
        # and look.
        unclaimed = [row for row in providers if str(row.get("id", "")) not in claimed]
        if unclaimed:
            self.stdout.write("")
            self.stdout.write(
                f"unclaimed   {len(unclaimed)} idp(s) in Zitadel that no row of ours names: "
                + ", ".join(sorted(str(row.get("name", "?")) for row in unclaimed))
            )

        # Two surfaces with no row behind them at all. They add nothing to
        # `drift` and they are the last thing before the blind-spot paragraph,
        # because what they narrow is exactly what that paragraph declares.
        self._report_console()
        return drift

    def _report_console(self) -> None:
        """The console's own surfaces: printed, and deliberately **not judged**.

        **Why observed rather than reconciled.** Every other line in this report
        starts from an intent — a `SsoConnection` row, or the environment the
        workforce door is switched by. The org's login policy and the instance's
        SMTP sender have neither: no product on this instance manages them
        through services, so there is nothing to disagree with. Reaching a drift
        VERDICT on them would mean inventing an intent row first, which is rule
        27's whole materialisation machinery built to guard a surface nothing
        writes. The ADR names the trigger that would change that (ADR ident-2's
        amendment: the first product managing login policy or SMTP through
        services). Until then the honest report is the value and who owns it.

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
        self.stdout.write("")
        self.stdout.write(
            "observed    the console's own surfaces — printed, not judged; no row "
            "states an intent for either, so neither can be drift"
        )

        try:
            policy = zitadel.login_policy()
        except zitadel.ZitadelError as error:
            self.stdout.write(f"  login-policy could not be read — {error}")
        else:
            self.stdout.write(f"  login-policy {self._login_policy_line(policy)}")

        try:
            smtp = zitadel.smtp_configuration()
        except zitadel.ZitadelError as error:
            self.stdout.write(f"  smtp         could not be read — {error}")
        else:
            self.stdout.write(f"  smtp         {self._smtp_line(smtp)}")

    @staticmethod
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

    @staticmethod
    def _smtp_line(smtp: dict[str, Any]) -> str:
        """One line for the instance's SMTP sender.

        Instance-wide, so on a shared development instance this names whoever
        configured it last — which is the fact worth printing and the reason this
        read is here at all. **No credential is on this line**: the API does not
        return the SMTP password, so there is none to leak into a report somebody
        will paste into a ticket.
        """
        if not smtp:
            return "no SMTP configuration on this instance"
        description = str(smtp.get("description", "") or "").strip()
        return (
            f"instance-wide — {smtp.get('senderName', '?')} "
            f"<{smtp.get('senderAddress', '?')}> via {smtp.get('host', '?')}, "
            f"{smtp.get('state', '?')}, id {smtp.get('id', '?')}"
            + (f"; described as {description!r}" if description else "")
        )

    def _report_blind_spot(self) -> None:
        """What a clean verdict does **not** cover, printed beside the verdict.

        This paragraph used to live in this module's docstring, where the person
        who most needs it — somebody reading a green report — never sees it. A
        blind spot declared only where the maintainer looks is a blind spot the
        operator does not have. So it prints, every run, both verdicts, in the
        one place a reader is already looking: immediately above the line that
        says whether the two agree.
        """
        self.stdout.write("does not cover")
        for line in (
            "  This compares what our ROWS declare, plus the workforce door the",
            "  environment declares. The observed section above is printed and not",
            "  judged: no row states an intent for a login policy or an SMTP sender,",
            "  so neither can disagree with anything and neither moves the exit code.",
            "  Still invisible: a second organisation, instance-level policy, actions,",
            "  machine keys, and any project or application no row of ours names — the",
            "  stranger IdPs are only counted, above, never inspected. So is anything",
            "  changed and changed back between two runs: this is a point-in-time read,",
            "  and running it again is the only diff there is.",
            "  House rule 27 fences this codebase. It cannot fence the console.",
        ):
            self.stdout.write(line)

    def _report_workforce(self, providers: list[dict[str, Any]]) -> tuple[int, str]:
        """The deployment's own door. Returns (disagreements, the idp id we claimed).

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
        `selectors.is_workforce_email` at the moment an assertion arrives,
        because a restriction expressed only in somebody else's console is a
        restriction we cannot test. So there is no per-domain set to diff — the
        report prints the list beside the provider and says where it is
        enforced, which is the true thing to print rather than a comparison
        against a field that does not exist.
        """
        name = workforce_idp_name()
        domains = workforce_domains()
        provider = next(
            (row for row in providers if str(row.get("name", "")) == name),
            None,
        )
        self.stdout.write("")

        if provider is None:
            if not domains:
                self.stdout.write(
                    f"workforce   off on both sides — GOOGLE_WORKSPACE_DOMAINS is empty "
                    f"and Zitadel holds no provider named {name!r}"
                )
                return 0, ""
            self.stdout.write(
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
            return 1, ""

        provider_id = str(provider.get("id", ""))
        if not domains:
            self.stdout.write(
                f"DRIFT       workforce — GOOGLE_WORKSPACE_DOMAINS is empty, so this "
                f"deployment refuses every workforce address, but Zitadel still holds "
                f"a live provider named {name!r} (idp {provider_id})"
            )
            return 1, provider_id

        expected_client = str(getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or "").strip()
        actual_client = zitadel.google_client_id_of(provider)
        if expected_client and actual_client and actual_client != expected_client:
            self.stdout.write(
                f"DRIFT       workforce — idp {provider_id} points at Google client "
                f"{actual_client!r}, this deployment is configured for "
                f"{expected_client!r}"
            )
            return 1, provider_id

        self.stdout.write(
            f"agrees      workforce — idp {provider_id}, domains {', '.join(domains)} "
            "(enforced here, not in Zitadel — ADR ident-6)"
        )
        return 0, provider_id
